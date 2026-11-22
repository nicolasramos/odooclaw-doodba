from odoo import api, models

BOT_PARAM = 'odooclaw_evolution.bot_partner_id'
BOT_USER_PARAM = 'mail_bot_odooclaw.bot_user_id'
API_USER_PARAM = 'odooclaw_evolution.api_user_id'


class OdooClawChat(models.AbstractModel):
    _name = 'odooclaw.chat'
    _description = 'OdooClaw chat bridge'

    @api.model
    def open_chat(self, model, res_id, view_type, field, request):
        partner = self.env.user.partner_id
        bot = self._bot_partner()
        commands = [(4, partner.id)]
        if bot and bot.id != partner.id:
            commands.append((4, bot.id))
        channel = self.env['discuss.channel'].create({
            'channel_type': 'chat',
            'channel_partner_ids': commands,
            'name': 'OdooClaw Live',
        })
        channel.message_post(
            body=self._body(model, res_id, view_type, field, request),
            message_type='comment',
            subtype_xmlid='mail.mt_comment',
        )
        return channel.id

    @api.model
    def _bot_partner(self):
        bot_id = self.env['ir.config_parameter'].sudo().get_param(BOT_PARAM)
        if bot_id:
            bot = self.env['res.partner'].sudo().browse(int(bot_id)).exists()
            if bot:
                return bot
        bot_user_id = self.env['ir.config_parameter'].sudo().get_param(BOT_USER_PARAM)
        if bot_user_id:
            bot_user = self.env['res.users'].sudo().browse(int(bot_user_id)).exists()
            if bot_user:
                return bot_user.partner_id
        api_user_id = self.env['ir.config_parameter'].sudo().get_param(API_USER_PARAM) or 2
        api_user = self.env['res.users'].sudo().browse(int(api_user_id)).exists()
        return api_user.partner_id if api_user else self.env.user.partner_id

    @api.model
    def _body(self, model, res_id, view_type, field, request):
        lines = ['OdooClaw Live']
        if model:
            lines.append('Modelo: %s' % model)
        if res_id:
            lines.append('Registro: %s' % res_id)
        if view_type:
            lines.append('Vista: %s' % view_type)
        if field:
            lines.append('Campo: %s' % field)
        if request:
            lines.append('')
            lines.append(request)
        return '\n'.join(lines)
