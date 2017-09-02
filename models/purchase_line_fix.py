# -*- coding: utf-8 -*-

from odoo import api, fields, models, _
from odoo.addons import decimal_precision as dp
from odoo.exceptions import UserError


class PurchaseLineFixPickingLine(models.TransientModel):
    _name = "purchase.line.fix.picking.line"
    _description = 'Purchase Line Fix Picking Line'
    _rec_name = 'product_id'

    product_id = fields.Many2one('product.product', string="Product", required=True)
    quantity = fields.Float("Correct Quantity", digits=dp.get_precision('Product Unit of Measure'), required=True)
    wizard_id = fields.Many2one('purchase.line.fix.picking', string="Wizard")
    move_id = fields.Many2one('stock.move', "Move")
    picking_id = fields.Many2one('stock.picking', "Transfer")


class PurchaseLineFixPicking(models.TransientModel):
    _name = "purchase.line.fix.picking"
    _description = 'Purchase Line Fix Picking'

    product_fix_moves = fields.One2many('purchase.line.fix.picking.line', 'wizard_id', 'Moves')


    @api.model
    def default_get(self, fields):
        res = super(PurchaseLineFixPicking, self).default_get(fields)

        Quant = self.env['stock.quant']
        product_fix_moves = []
        purchase_line = self.env['purchase.order.line'].browse(self.env.context.get('active_id'))
        for move in purchase_line.move_ids:
            if move.state != 'done':
                continue
            if move.location_dest_id.usage != 'internal':
                continue
            if move.scrapped:
                continue
            quantity = sum(quant.qty for quant in Quant.search([
                ('history_ids', 'in', move.id),
                ('qty', '>', 0.0)
            ]).filtered(
                lambda quant: not quant.reservation_id or quant.reservation_id.origin_returned_move_id != move)
            )
            quantity = move.product_id.uom_id._compute_quantity(quantity, move.product_uom)
            product_fix_moves.append((0, 0, {'product_id': move.product_id.id, 'quantity': quantity, 'move_id': move.id,'picking_id': move.picking_id.id}))
            picking = move.picking_id

        if not product_fix_moves:
            raise UserError(_("No moves to fix (only lines in Done state can be fixed)!"))
        if 'product_fix_moves' in fields:
            res.update({'product_fix_moves': product_fix_moves})
        return res

    @api.multi
    def create_fix(self):
        for wizard in self:
            for line in wizard.product_fix_moves:
                difference = line.quantity - line.move_id.product_uom_qty
                line.move_id.sudo().write({'product_uom_qty': line.quantity})
                for quant in line.move_id.quant_ids:
                    if quant.location_id.usage == 'internal':
                        new_quant = quant.qty + difference
                        quant.sudo().write({'qty': new_quant})
                        if new_quant < 0:
                            #negative_moves = line.move_id.quant_ids.filtered(lambda quant: not quant.location_id != 'internal'))
                            quant.sudo().write({'negative_move_id': 171,'negative_dest_location_id': 9})


                line.move_id.linked_move_operation_ids[0].operation_id.sudo().write({'qty_done':line.quantity})
                #links = self.env['stock.move.operation.link'].search(['id','in',line.move_id.linked_move_operation_ids.ids])
                #links[0].operation_id.write({'qty_done':line.quantity})
            moves = wizard.product_fix_moves.mapped(lambda r: r.move_id.id)
            purchase_lines = self.env['purchase.order.line'].search([('move_ids','in',moves)])
            for line in purchase_lines:
                if line.order_id.state not in ['purchase', 'done']:
                    line.qty_received = 0.0
                    continue
                if line.product_id.type not in ['consu', 'product']:
                    line.qty_received = line.product_qty
                    continue
                total = 0.0
                for move in line.move_ids:
                    if move.state == 'done':
                        if move.product_uom != line.product_uom:
                            total += move.product_uom._compute_quantity(move.product_uom_qty, line.product_uom)
                        else:
                            total += move.product_uom_qty
                line.qty_received = total
