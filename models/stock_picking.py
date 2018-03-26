# -*- coding: utf-8 -*-

from odoo import api, fields, models, _
from odoo.exceptions import UserError


class Picking(models.Model):
    _inherit = 'stock.picking'

    auto_confirm = fields.Boolean(string='Auto Confirm',store=True)

    @api.onchange('auto_confirm')
    def _auto_confirm(self):
        for record in self:
            if record.auto_confirm == True:
                record.action_confirm()
