# -*- coding: utf-8 -*-

from odoo import api, fields, models, _
from odoo.exceptions import UserError

class ProductTemplate(models.Model):
    _inherit = "product.template"

    supplier_codes = fields.Char(string='Supplier Codes',compute="_compute_supplier_codes",store=True)

    @api.depends('seller_ids')
    def _compute_supplier_codes(self):
        for record in self:
            record.supplier_codes = str(record.seller_ids.mapped('product_code'))
