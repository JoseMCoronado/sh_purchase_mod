# -*- coding: utf-8 -*-

from odoo import api, fields, models, _
from odoo.addons import decimal_precision as dp
from odoo.exceptions import UserError


class PurchaseLineReturnPickingLine(models.TransientModel):
    _name = "purchase.line.return.picking.line"
    _description = 'Purchase Line Return Picking Line'
    _rec_name = 'product_id'

    product_id = fields.Many2one('product.product', string="Product", required=True)
    quantity = fields.Float("Quantity", digits=dp.get_precision('Product Unit of Measure'), required=True)
    wizard_id = fields.Many2one('purchase.line.return.picking', string="Wizard")
    move_id = fields.Many2one('stock.move', "Move")


class PurchaseLineReturnPicking(models.TransientModel):
    _name = 'purchase.line.return.picking'
    _description = 'Purchase Line Return Picking'

    product_return_moves = fields.One2many('purchase.line.return.picking.line', 'wizard_id', 'Moves')
    move_dest_exists = fields.Boolean('Chained Move Exists', readonly=True)
    original_location_id = fields.Many2one('stock.location')
    parent_location_id = fields.Many2one('stock.location')
    location_id = fields.Many2one(
        'stock.location', 'Return Location',
        domain="['|', ('id', '=', original_location_id), '&', ('return_location', '=', True), ('id', 'child_of', parent_location_id)]")

    @api.model
    def default_get(self, fields):
        res = super(PurchaseLineReturnPicking, self).default_get(fields)

        Quant = self.env['stock.quant']
        move_dest_exists = False
        product_return_moves = []
        purchase_line = self.env['purchase.order.line'].browse(self.env.context.get('active_id'))
        #search_pickings = purchase_line.move_ids.filtered(lambda r: not r.backorder_id and r.scrapped != True and r.is_done == True).mapped('picking_id.id')
        #picking = self.env['stock.picking'].search([('id','in',search_pickings)],limit=1)
        #if picking:
        #    if picking.state != 'done':
        #        raise UserError(_("You may only return Done pickings"))
        for move in purchase_line.move_ids:
            if move.state != 'done':
                continue
            if move.scrapped:
                continue
            if move.move_dest_id:
                move_dest_exists = True
            # Sum the quants in that location that can be returned (they should have been moved by the moves that were included in the returned picking)
            quantity = sum(quant.qty for quant in Quant.search([
                ('history_ids', 'in', move.id),
                ('qty', '>', 0.0), ('location_id', 'child_of', move.location_dest_id.id)
            ]).filtered(
                lambda quant: not quant.reservation_id or quant.reservation_id.origin_returned_move_id != move)
            )
            quantity = move.product_id.uom_id._compute_quantity(quantity, move.product_uom)
            product_return_moves.append((0, 0, {'product_id': move.product_id.id, 'quantity': quantity, 'move_id': move.id}))
            picking = move.picking_id

        if not product_return_moves:
            raise UserError(_("No products to return (only lines in Done state and not fully returned yet can be returned)!"))
        if 'product_return_moves' in fields:
            res.update({'product_return_moves': product_return_moves})
        if 'move_dest_exists' in fields:
            res.update({'move_dest_exists': move_dest_exists})
        if 'parent_location_id' in fields and picking.location_id.usage == 'internal':
            res.update({'parent_location_id': picking.picking_type_id.warehouse_id and picking.picking_type_id.warehouse_id.view_location_id.id or picking.location_id.location_id.id})
        if 'original_location_id' in fields:
            res.update({'original_location_id': picking.location_id.id})
        if 'location_id' in fields:
            location_id = picking.location_id.id
            if picking.picking_type_id.return_picking_type_id.default_location_dest_id.return_location:
                location_id = picking.picking_type_id.return_picking_type_id.default_location_dest_id.id
            res['location_id'] = location_id
        return res

    @api.multi
    def _create_returns(self):

        return_moves = self.product_return_moves.mapped('move_id')
        return_moves_id = return_moves[0].ids
        picking = self.env['stock.picking'].search([('move_lines','in',return_moves_id)])
        unreserve_moves = self.env['stock.move']
        for move in return_moves:
            to_check_moves = self.env['stock.move'] | move.move_dest_id
            while to_check_moves:
                current_move = to_check_moves[-1]
                to_check_moves = to_check_moves[:-1]
                if current_move.state not in ('done', 'cancel') and current_move.reserved_quant_ids:
                    unreserve_moves |= current_move
                split_move_ids = self.env['stock.move'].search([('split_from', '=', current_move.id)])
                to_check_moves |= split_move_ids

        if unreserve_moves:
            unreserve_moves.do_unreserve()
            # break the link between moves in order to be able to fix them later if needed
            unreserve_moves.write({'move_orig_ids': False})

        # create new picking for returned products
        picking_type_id = picking.picking_type_id.return_picking_type_id.id or picking.picking_type_id.id
        new_picking = picking.copy({
            'move_lines': [],
            'picking_type_id': picking_type_id,
            'state': 'draft',
            'origin': picking.name,
            'location_id': picking.location_dest_id.id,
            'location_dest_id': self.location_id.id})
        new_picking.message_post_with_view('mail.message_origin_link',
            values={'self': new_picking, 'origin': picking},
            subtype_id=self.env.ref('mail.mt_note').id)

        returned_lines = 0
        for return_line in self.product_return_moves:
            if not return_line.move_id:
                raise UserError(_("You have manually created product lines, please delete them to proceed"))
            new_qty = return_line.quantity
            if new_qty:
                # The return of a return should be linked with the original's destination move if it was not cancelled
                if return_line.move_id.origin_returned_move_id.move_dest_id.id and return_line.move_id.origin_returned_move_id.move_dest_id.state != 'cancel':
                    move_dest_id = return_line.move_id.origin_returned_move_id.move_dest_id.id
                else:
                    move_dest_id = False

                returned_lines += 1
                return_line.move_id.copy({
                    'product_id': return_line.product_id.id,
                    'product_uom_qty': new_qty,
                    'picking_id': new_picking.id,
                    'state': 'draft',
                    'location_id': return_line.move_id.location_dest_id.id,
                    'location_dest_id': self.location_id.id or return_line.move_id.location_id.id,
                    'picking_type_id': picking_type_id,
                    'warehouse_id': picking.picking_type_id.warehouse_id.id,
                    'origin_returned_move_id': return_line.move_id.id,
                    'procure_method': 'make_to_stock',
                    'move_dest_id': move_dest_id,
                })

        if not returned_lines:
            raise UserError(_("Please specify at least one non-zero quantity."))

        new_picking.action_confirm()
        new_picking.action_assign()
        return new_picking.id, picking_type_id

    @api.multi
    def create_returns(self):
        for wizard in self:
            new_picking_id, pick_type_id = wizard._create_returns()
        # Override the context to disable all the potential filters that could have been set previously
        ctx = dict(self.env.context)
        ctx.update({
            'search_default_picking_type_id': pick_type_id,
            'search_default_draft': False,
            'search_default_assigned': False,
            'search_default_confirmed': False,
            'search_default_ready': False,
            'search_default_late': False,
            'search_default_available': False,
        })
        return {
            'name': _('Returned Picking'),
            'view_type': 'form',
            'view_mode': 'form,tree,calendar',
            'res_model': 'stock.picking',
            'res_id': new_picking_id,
            'type': 'ir.actions.act_window',
            'context': ctx,
}