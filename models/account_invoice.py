# -*- coding: utf-8 -*-

from odoo import api, fields, models, _
from odoo.exceptions import UserError

class AccountInvoiceLine(models.Model):
    _inherit = "account.invoice.line"

    qty_received = fields.Float(string='Received Qty',compute="_compute_received",store=False,readonly=True)

    @api.multi
    def _compute_received(self):
        for record in self:
            receivedqty = 0
            for poline in record.purchase_line_id:
                receivedqty += poline.qty_received
            record.qty_received = receivedqty

    @api.multi
    def open_adjustment_wizard(self):
        for record in self:
            action_data = record.env.ref('sh_purchase_mod.action_adjust_subtotal').read()[0]
            action_data.update({'context':{'default_invoice_line_id':record.id}})
            return action_data

class AdjustUnitPriceWizard(models.TransientModel):
    _name = "adjust.unit.price.wizard"
    _description = "Adjust Unit Price Wizard"

    invoice_line_id = fields.Many2one('account.invoice.line',string="Invoice Line")
    amount = fields.Float(string="Desired Subtotal")

    @api.multi
    def adjust_line(self):
        for record in self:
            if record.invoice_line_id.quantity >0:
                record.invoice_line_id.price_unit = (record.amount / record.invoice_line_id.quantity)
