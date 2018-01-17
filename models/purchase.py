# -*- coding: utf-8 -*-

from datetime import datetime
from dateutil.relativedelta import relativedelta

from odoo.tools.float_utils import float_is_zero, float_compare
from odoo.tools import DEFAULT_SERVER_DATETIME_FORMAT
from lxml import etree
from odoo import api, fields, models, SUPERUSER_ID, _
from odoo.exceptions import UserError, AccessError
from odoo.tools.misc import formatLang
from odoo.addons.base.res.res_partner import WARNING_MESSAGE, WARNING_HELP
import odoo.addons.decimal_precision as dp

class PurchaseOrder(models.Model):
    _inherit = "purchase.order"

    @api.multi
    def action_view_picking(self):

        action = self.env.ref('sh_purchase_mod.action_purchase_picking_tree')
        result = action.read()[0]

        result.pop('id', None)
        result['context'] = {}
        pick_ids = sum([order.picking_ids.ids for order in self], [])

        if len(pick_ids) > 1:
            result['domain'] = "[('id','in',[" + ','.join(map(str, pick_ids)) + "])]"
        elif len(pick_ids) == 1:
            res = self.env.ref('stock.view_picking_form', False)
            result['views'] = [(res and res.id or False, 'form')]
            result['res_id'] = pick_ids and pick_ids[0] or False
        return result

    @api.multi
    def action_view_avl_picking(self):

        action = self.env.ref('sh_purchase_mod.action_purchase_picking_tree')
        result = action.read()[0]

        result.pop('id', None)
        result['context'] = {}

        for order in self:
            avl_pick_ids = order.picking_ids.filtered(lambda r: r.state in ['confirmed','partially_available','assigned']).ids

        pick_ids = sum([order.picking_ids.ids for order in self], [])

        if len(avl_pick_ids) < 1 and len(pick_ids) > 1:
            result['domain'] = "[('id','in',[" + ','.join(map(str, pick_ids)) + "])]"
        elif len(avl_pick_ids) > 0:
            res = self.env.ref('stock.view_picking_form', False)
            result['views'] = [(res and res.id or False, 'form')]
            result['res_id'] = avl_pick_ids[0] or False
        return result


class PurchaseOrderLine(models.Model):
    _inherit = "purchase.order.line"

    @api.depends('order_id.state', 'move_ids.state','move_ids.returned_move_ids.state','move_ids.picking_id.move_lines.state','move_ids.returned_move_ids.picking_id.move_lines.state')
    def _compute_qty_received(self):
        for line in self:
            if line.order_id.state not in ['purchase', 'done']:
                line.qty_received = 0.0
                continue
            if line.product_id.type not in ['consu', 'product']:
                line.qty_received = line.product_qty
                continue
            total = 0.0
            total_neg = 0.0
            moves = line.move_ids | line.move_ids.mapped('returned_move_ids')
            ##TODO FIX THE ISSUE WITH RETURNED MOVE IDS
            for move in moves:
                if move.state == 'done' and move.product_id == line.product_id and move.scrapped != True:
                    if move.location_dest_id.usage == 'internal':
                        if move.product_uom != line.product_uom:
                            total += move.product_uom._compute_quantity(move.product_uom_qty, line.product_uom)
                        else:
                            total += move.product_uom_qty
                    else:
                        if move.product_uom != line.product_uom:
                            total_neg += move.product_uom._compute_quantity(move.product_uom_qty, line.product_uom)
                        else:
                            total_neg += move.product_uom_qty
            line.qty_received = total - total_neg

    @api.multi
    def button_scrap(self):
        self.ensure_one()
        for move in self.move_ids:
            if move.state != 'done':
                continue
            if move.scrapped:
                continue
            picking = move.picking_id
        if picking:
            return {
                'name': 'Scrap',
                'view_type': 'form',
                'view_mode': 'form',
                'res_model': 'stock.scrap',
                'view_id': self.env.ref('stock.stock_scrap_form_view2').id,
                'type': 'ir.actions.act_window',
                'context': {'default_picking_id': picking.id, 'default_product_id': self.product_id.id},
                'target': 'new',
            }
        else:
            raise UserError(_("No moves available to scrap."))

    @api.multi
    def unlink(self):
        for line in self:
            if line.order_id.state in ['purchase', 'done']:
                raise UserError(_('Cannot delete a purchase order line which is in state \'%s\'.') %(line.state,))
            proc_ids = []
            for proc in line.procurement_ids:
                proc.message_post(body=_('Purchase order line deleted.'))
                proc_ids.append(proc.id)
                proc.purchase_line_id = False
            line.env['procurement.order'].browse(proc_ids).filtered(lambda r: r.state != 'cancel').cancel()
        return super(PurchaseOrderLine, self).unlink()

class ProcurementOrder(models.Model):
    _inherit = 'procurement.order'

    @api.multi
    def _prepare_purchase_order_line(self, po, supplier):
        self.ensure_one()

        procurement_uom_po_qty = self.product_uom._compute_quantity(self.product_qty, self.product_id.uom_po_id)
        seller = self.product_id._select_seller(
            partner_id=supplier.name,
            quantity=procurement_uom_po_qty,
            date=po.date_order and po.date_order[:10],
            uom_id=self.product_id.uom_po_id)

        taxes = self.product_id.supplier_taxes_id
        fpos = po.fiscal_position_id
        taxes_id = fpos.map_tax(taxes) if fpos else taxes
        if taxes_id:
            taxes_id = taxes_id.filtered(lambda x: x.company_id.id == self.company_id.id)

        price_unit = self.env['account.tax']._fix_tax_included_price_company(seller.price, self.product_id.supplier_taxes_id, taxes_id, self.company_id) if seller else 0.0
        if price_unit and seller and po.currency_id and seller.currency_id != po.currency_id:
            price_unit = seller.currency_id.compute(price_unit, po.currency_id)

        product_lang = self.product_id.with_context({
            'lang': supplier.name.lang,
            'partner_id': supplier.name.id,
        })
        ##NAME CHANGE##
        if supplier and (supplier.product_name or supplier.product_code):
            name = ""
            if supplier.product_code:
                name = "[" + supplier.product_code + "] "
            if supplier.product_name:
                name += supplier.product_name
            else:
                name += self.product_id.name
        else:
            name = self.product_id.name

        if product_lang.description_purchase:
            name += '\n' + product_lang.description_purchase

        date_planned = self.env['purchase.order.line']._get_date_planned(seller, po=po).strftime(DEFAULT_SERVER_DATETIME_FORMAT)

        return {
            'name': name,
            'product_qty': procurement_uom_po_qty,
            'product_id': self.product_id.id,
            'product_uom': self.product_id.uom_po_id.id,
            'price_unit': price_unit,
            'date_planned': date_planned,
            'taxes_id': [(6, 0, taxes_id.ids)],
            'procurement_ids': [(4, self.id)],
            'order_id': po.id,
        }

class Picking(models.Model):
    _inherit = "stock.picking"

    return_id = fields.Many2one(
        'stock.picking', 'Return of',
        copy=False, index=True,
        states={'done': [('readonly', True)], 'cancel': [('readonly', True)]})
    transfer_type = fields.Selection([
        ('receipt', 'Receipt'),
        ('delivery', 'Dispatch'),
        ('return', 'Return'),
        ('internal', 'Internal'),
        ('scrap', 'Scrap')],
        readonly=True, compute='_compute_transfer_type')
    pack_operation_product_ids = fields.One2many(
        'stock.pack.operation', 'picking_id', 'Non pack',
        domain=[('product_id', '!=', False)],
        states={'done': [('readonly', False)], 'cancel': [('readonly', True)]})
    dest_address_id = fields.Many2one(
        'res.partner', 'Dropship Address',
        copy=False, index=True, store=False, readonly=True,compute='_compute_dsaddress')

    @api.multi
    def _compute_dsaddress(self):
        for picking in self:
            if picking.purchase_id and picking.purchase_id.dest_address_id:
                picking.dest_address_id = picking.purchase_id.dest_address_id

    @api.one
    def _compute_transfer_type(self):
        if self.return_id:
            self.transfer_type = 'return'
        elif self.location_dest_id.id == self.env.ref('stock.stock_location_scrapped').id:
            self.transfer_type = 'scwrap'
        elif self.location_dest_id.usage == 'internal' and self.location_id.usage == 'internal':
            self.transfer_type = 'internal'
        elif self.location_dest_id.usage == 'internal' and self.location_id.usage != 'internal':
            self.transfer_type = 'receipt'
        else:
            self.transfer_type = 'delivery'

class ReturnPicking(models.TransientModel):
    _inherit = "stock.return.picking"

    @api.multi
    def _create_returns(self):
        res = super(ReturnPicking, self)._create_returns()

        new_picking = self.env['stock.picking'].browse(res[0])
        picking = self.env['stock.picking'].browse(self.env.context['active_id'])

        new_picking.return_id = picking.id

        return res

class PackOperation(models.Model):
    _inherit = "stock.pack.operation"

    @api.multi
    @api.constrains('qty_done')
    def do_fix(self):
        for operation in self:
            picking = operation.picking_id
            if picking.state == 'done':
                moves = operation.picking_id.move_lines.filtered(lambda x: x.product_id == operation.product_id)
                quant_total = 0
                total = 0
                total_neg = 0
                if moves:
                    purchase_line = moves[0].purchase_line_id
                for move in moves:
                    if move.state == 'done' and move.scrapped != True:
                        if move.location_dest_id == picking.location_dest_id:
                                total += move.product_uom_qty
                        else:
                                total_neg += move.product_uom_qty
                quant_total = total - total_neg

                if quant_total > operation.qty_done:
                    new_move_vals = {
                        'name': str(picking.name) + ' Move Fix',
                        'origin': picking.name,
                        'product_id': operation.product_id.id,
                        'product_uom': operation.product_id.uom_id.id,
                        'product_uom_qty': quant_total - operation.qty_done,
                        'location_id': picking.location_dest_id.id,
                        'location_dest_id': picking.location_id.id,
                        'picking_id': picking.id,
                        'purchase_line_id': purchase_line.id
                    }
                else:
                    new_move_vals = {
                        'name': str(picking.name) + ' Move Fix',
                        'origin': picking.name,
                        'product_id': operation.product_id.id,
                        'product_uom': operation.product_id.uom_id.id,
                        'product_uom_qty': operation.qty_done - quant_total,
                        'location_id': picking.location_id.id,
                        'location_dest_id': picking.location_dest_id.id,
                        'picking_id': picking.id,
                        'purchase_line_id': purchase_line.id
                    }
                move = operation.env['stock.move'].create(new_move_vals)
                quants = operation.env['stock.quant'].quants_get_preferred_domain(
                move.product_qty, move,
                domain=[
                    ('qty', '>', 0),
                    #('lot_id', '=', self.lot_id.id),
                    ('package_id', '=', operation.package_id.id)],
                preferred_domain_list=operation._get_preferred_domain())

                if any([not x[0] for x in quants]):
                    quants_new = quants = operation.env['stock.quant'].quants_get_preferred_domain(
                    move.product_qty, move,
                    domain=[
                        ('qty', '>', 0),
                        #('lot_id', '=', self.lot_id.id),
                        ('package_id', '=', operation.package_id.id)],
                    preferred_domain_list=[])
                else:
                    quants_new = quants
                operation.env['stock.quant'].quants_reserve(quants_new, move)
                move.action_done()
                moves.recalculate_move_state()

    def _get_preferred_domain(self):
        if not self.picking_id:
            return []
        if self.picking_id.state == 'done':
            preferred_domain = [('history_ids', 'in', self.picking_id.move_lines.filtered(lambda x: x.state == 'done').ids)]
            preferred_domain2 = [('history_ids', 'not in', self.picking_id.move_lines.filtered(lambda x: x.state == 'done').ids)]
            return [preferred_domain, preferred_domain2]
