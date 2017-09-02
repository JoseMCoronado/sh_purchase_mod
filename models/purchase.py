# -*- coding: utf-8 -*-

from odoo.tools.float_utils import float_compare
from lxml import etree
from odoo import api, fields, models
from odoo.exceptions import UserError

class PurchaseOrder(models.Model):
    _inherit = "purchase.order"

    show_backorder = fields.Boolean(string='Show Backorders',
    compute='_show_backorder', readonly=True,
    store=False)
    show_returned = fields.Boolean(string='Show Returns',
    compute='_show_returned', readonly=True,
    store=False)
    show_scrapped = fields.Boolean(string='Show Scrapped',
    compute='_show_scrapped', readonly=True,
    store=False)


    def _show_backorder(self):
        if any(self.order_line.mapped(lambda r: r.backorder_qty > 0)):
            group_id = self.env.ref('sh_purchase_mod.group_show_backorder').id
            group = self.env['res.groups'].search([('id','=',group_id)])
            group.write({'users': [(4, self.env.user.id)]})
            self.show_backorder = True
        else:
            group_id = self.env.ref('sh_purchase_mod.group_show_backorder').id
            group = self.env['res.groups'].search([('id','=',group_id)])
            group.write({'users': [(3, self.env.user.id)]})
            self.show_backorder = False

    def _show_returned(self):
        if any(self.order_line.mapped(lambda r: r.returned_qty > 0)):
            group_id = self.env.ref('sh_purchase_mod.group_show_returns').id
            group = self.env['res.groups'].search([('id','=',group_id)])
            group.write({'users': [(4, self.env.user.id)]})
            self.show_returned = True
        else:
            group_id = self.env.ref('sh_purchase_mod.group_show_returns').id
            group = self.env['res.groups'].search([('id','=',group_id)])
            group.write({'users': [(3, self.env.user.id)]})
            self.show_returned = False

    def _show_scrapped(self):
        if any(self.order_line.mapped(lambda r: r.scrapped_qty > 0)):
            group_id = self.env.ref('sh_purchase_mod.group_show_scrapped').id
            group = self.env['res.groups'].search([('id','=',group_id)])
            group.write({'users': [(4, self.env.user.id)]})
            self.show_scrapped = True
        else:
            group_id = self.env.ref('sh_purchase_mod.group_show_scrapped').id
            group = self.env['res.groups'].search([('id','=',group_id)])
            group.write({'users': [(3, self.env.user.id)]})
            self.show_scrapped = False


class PurchaseOrderLine(models.Model):
    _inherit = "purchase.order.line"

    backorder_qty = fields.Float(string='Backorder Qty',
    compute='_get_backorder_qty', readonly=True,
    store=False)
    returned_qty = fields.Float(string='Returned Qty',
    compute='_get_returned_qty', readonly=True,
    store=False)
    scrapped_qty = fields.Float(string='Scrapped Qty',
    compute='_get_scrapped_qty', readonly=True,
    store=False)
    accepted_qty = fields.Float(string='Accepted Qty',
    compute='_compute_accepted_qty', readonly=True,
    store=False)

    @api.model
    def _get_backorder_qty(self):
        for line in self:
            backorder_amount = 0
            backorder_amount += sum(line.move_ids.filtered(lambda r: r.backorder_id and r.is_done != True).mapped(lambda r: r.product_uom_qty))
            line.backorder_qty = backorder_amount

    @api.model
    def _get_returned_qty(self):
        for line in self:
            returned_amount = 0
            for m in line.move_ids:
                returned_amount += sum(m.returned_move_ids.filtered(lambda r: r.is_done == True).mapped(lambda r: r.product_uom_qty))
            line.returned_qty = returned_amount

    @api.model
    def _get_scrapped_qty(self):
        for line in self:
            scrapped_amount = 0
            for p in line.order_id.picking_ids:
                scrapped_amount += sum(p.move_lines.filtered(lambda r: r.scrapped == True).mapped(lambda r: r.product_uom_qty))
            line.scrapped_qty = scrapped_amount

    @api.model
    def _compute_accepted_qty(self):
        for line in self:
            line.accepted_qty = line.qty_received - (line.backorder_qty + line.returned_qty + line.scrapped_qty)

    @api.onchange('product_id')
    def onchange_product_id(self):
        super(PurchaseOrderLine, self).onchange_product_id()
        for line in self:
            line.name = line.product_id.name
            if line.product_id.description_purchase:
                line.name += '\n' + line.product_id.description_purchase

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
            raise UserError(_("No moves avaialble to scrap."))

class AccountInvoice(models.Model):
    _inherit = 'account.invoice'

    def _prepare_invoice_line_from_po_line(self, line):
        if line.product_id.purchase_method == 'purchase':
            qty = line.accepted_qty - line.qty_invoiced
        else:
            qty = line.accepted_qty - line.qty_invoiced
        if float_compare(qty, 0.0, precision_rounding=line.product_uom.rounding) <= 0:
            qty = 0.0
        taxes = line.taxes_id
        invoice_line_tax_ids = line.order_id.fiscal_position_id.map_tax(taxes)
        invoice_line = self.env['account.invoice.line']
        data = {
            'purchase_line_id': line.id,
            'name': line.order_id.name+': '+line.name,
            'origin': line.order_id.origin,
            'uom_id': line.product_uom.id,
            'product_id': line.product_id.id,
            'account_id': invoice_line.with_context({'journal_id': self.journal_id.id, 'type': 'in_invoice'})._default_account(),
            'price_unit': line.order_id.currency_id.compute(line.price_unit, self.currency_id, round=False),
            'quantity': qty,
            'discount': 0.0,
            'account_analytic_id': line.account_analytic_id.id,
            'analytic_tag_ids': line.analytic_tag_ids.ids,
            'invoice_line_tax_ids': invoice_line_tax_ids.ids
        }
        account = invoice_line.get_invoice_line_account('in_invoice', line.product_id, line.order_id.fiscal_position_id, self.env.user.company_id)
        if account:
            data['account_id'] = account.id
        return data

class PackOperation(models.Model):
    _inherit = "stock.pack.operation"

    @api.multi
    def _compute_location_description(self):
        for operation, operation_sudo in zip(self, self.sudo()):
            operation.from_loc = '%s%s' % (operation_sudo.location_id.name, operation.product_id and operation_sudo.package_id.name or '')
            operation.to_loc = '%s%s' % (operation_sudo.location_dest_id.name, operation_sudo.result_package_id.name or '')
