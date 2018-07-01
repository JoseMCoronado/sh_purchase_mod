# -*- coding: utf-8 -*-

from odoo import api, fields, models, _
from odoo.exceptions import UserError

class ProductTemplate(models.Model):
    _inherit = "product.template"

    supplier_codes = fields.Char(string='Supplier Codes',compute="_compute_supplier_codes",store=True)
    shipping_cost = fields.Float(string="Shipping Cost")
    total_cost = fields.Float(string="Total Cost",compute="_compute_total_cost",store=True,readonly=True)

    @api.depends('shipping_cost','standard_price')
    def _compute_total_cost(self):
        for record in self:
            record.total_cost = record.shipping_cost + record.standard_price


class ProductProduct(models.Model):
    _inherit = "product.product"

    shipping_cost = fields.Float(string="Shipping Cost",related="product_tmpl_id.shipping_cost")
    total_cost = fields.Float(string="Total Cost",related="product_tmpl_id.total_cost", store=True,readonly=True)
