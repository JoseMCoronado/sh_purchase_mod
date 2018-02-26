# -*- coding: utf-8 -*-

from odoo import api, fields, models, _
from odoo.exceptions import UserError

class AccountInvoiceLine(models.Model):
    _inherit = "account.invoice.line"

    qty_received = fields.Float(string='Received Qty',compute="_compute_received",readonly="True",store="False")

    @api.multi
    def _compute_received(self):
        for record in self:
            receivedqty = 0
            for poline in record.purchase_line_id:
                receivedqty += poline.qty_received
            record.qty_received = receivedqty
