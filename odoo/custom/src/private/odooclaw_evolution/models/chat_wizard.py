from odoo import fields, models


class OdooClawChatWizard(models.TransientModel):
    _name = 'odooclaw.chat.wizard'
    _description = 'OdooClaw Live chat wizard'

    model = fields.Char(default='')
    res_id = fields.Integer(default=0)
    view_type = fields.Char(default='form')
    field = fields.Char(default='')
    request = fields.Text(string='¿Qué quieres cambiar?')

    def action_open_chat(self):
        self.ensure_one()
        channel_id = self.env['odooclaw.chat'].open_chat(
            self.model or '',
            self.res_id or 0,
            self.view_type or '',
            self.field or '',
            self.request or '',
        )
        channel = self.env['discuss.channel'].browse(channel_id)
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'OdooClaw Live',
                'message': 'Chat "%s" creado. Ábrelo en Discuss.' % channel.name,
                'type': 'success',
                'sticky': False,
                'next': {'type': 'ir.actions.act_window_close'},
            },
        }
