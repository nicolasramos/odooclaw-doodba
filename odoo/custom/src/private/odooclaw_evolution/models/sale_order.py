from odoo import models


class SaleOrder(models.Model):
    _inherit = 'sale.order'

    def action_odooclaw_wizard(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'OdooClaw Live',
            'res_model': 'odooclaw.chat.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_model': self._name,
                'default_res_id': self.id,
                'default_view_type': 'form',
                'default_field': 'x_margin_preview',
            },
        }
