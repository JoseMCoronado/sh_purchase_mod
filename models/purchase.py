# -*- coding: utf-8 -*-

from odoo.tools.float_utils import float_compare
from lxml import etree
from odoo import api, fields, models
from odoo.exceptions import UserError
from odoo.addons import decimal_precision as dp

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
            pickings = self.env['stock.picking']
            moves = line.move_ids | line.move_ids.mapped('returned_move_ids')
            pickings |= moves.mapped('picking_id')
            for picking in pickings:
                for move in picking.move_lines:
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

    fixed = fields.Boolean(string='Fixed', store=True, readonly=True, compute='do_fix')

    #def _get_origin_moves(self):
    #    return self.picking_id and self.picking_id.move_lines.filtered(lambda x: x.product_id == self.product_id)

    @api.depends('qty_done')
    def do_fix(self):
        for operation in self:
            picking = operation.picking_id
            if picking.state == 'done':
                moves = operation.picking_id.move_lines.filtered(lambda x: x.product_id == operation.product_id)
                quant_total = 0
                total = 0
                total_neg = 0
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
                        'picking_id': picking.id
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
                        'picking_id': picking.id
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
                operation.fixed = True

    def _get_preferred_domain(self):
        if not self.picking_id:
            return []
        if self.picking_id.state == 'done':
            preferred_domain = [('history_ids', 'in', self.picking_id.move_lines.filtered(lambda x: x.state == 'done').ids)]
            preferred_domain2 = [('history_ids', 'not in', self.picking_id.move_lines.filtered(lambda x: x.state == 'done').ids)]
            return [preferred_domain, preferred_domain2]

    ##FIX FOR STAGING SERVER ERROR##
    @api.multi
    def _compute_location_description(self):
        for operation, operation_sudo in zip(self, self.sudo()):
            operation.from_loc = '%s%s' % (operation_sudo.location_id.name, operation.product_id and operation_sudo.package_id.name or '')
            operation.to_loc = '%s%s' % (operation_sudo.location_dest_id.name, operation_sudo.result_package_id.name or '')
