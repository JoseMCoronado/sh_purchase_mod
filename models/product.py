# -*- coding: utf-8 -*-

from odoo import api, fields, models, _
from odoo.exceptions import UserError

class ProductTemplate(models.Model):
    _inherit = "product.template"

    supplier_codes = fields.Char(string='Supplier Codes',compute="_compute_supplier_codes",store=True)

    cost_type = fields.Selection([
        ('manufacture', 'Manufactured In-House'),
        ('purchase', 'Purchased'),
        ],
        string="Cost Type",default='manufacture')
    shipping_cost = fields.Float(string="Shipping Cost")
    purchase_cost = fields.Float(string="Purchase Cost")
    bom_cost = fields.Float(string="Subtotal from BoM",compute="_update_bom_subtotal",store=True)

    @api.constrains('shipping_cost','cost_type','purchase_cost','bom_cost')
    def update_standard_price(self):
        for record in self:
            if record.cost_type == 'manufacture':
                record.standard_price = record.bom_cost
            elif record.cost_type == 'purchase':
                record.standard_price = record.shipping_cost + record.purchase_cost

    @api.depends('bom_ids','bom_ids.bom_line_ids','bom_ids.bom_line_ids.product_id','bom_ids.bom_line_ids.product_id.standard_price')
    def _update_bom_subtotal(self):
        for record in self:
            if record.bom_ids:
                bom = record.bom_ids[0]
                total_cost = 0
                for l in bom.bom_line_ids:
                    total_cost += (l.product_id.standard_price * l.product_qty)
                record.bom_cost = total_cost

class ProductProduct(models.Model):
    _inherit = "product.product"

    shipping_cost = fields.Float(string="Shipping Cost",related="product_tmpl_id.shipping_cost")
    purchase_cost = fields.Float(string="Purchase Cost",related="product_tmpl_id.purchase_cost")
    bom_cost = fields.Float(string="Subtotal from BoM",related="product_tmpl_id.bom_cost")
