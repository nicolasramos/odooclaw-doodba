"""End-to-end demo check for the OdooClaw Coolify demo.

Exercises the real conversation chain inside the running stack:
  Discuss DM (message_post) -> mail_bot_odooclaw webhook -> OdooClaw gateway
  -> odoo-mcp ORM tools over XML-RPC -> POST /odooclaw/reply -> Discuss reply

Run inside the Odoo container:
  docker exec -u odoo <odoo> sh -c 'cat /tmp/e2e_check.py | odoo shell -d demo --no-http'

Note: the channel must be created as a real user. Odoo 18 auto-adds the creating
user as a member, so creating it as __system__ (odoo shell's default user) adds a
third partner and trips discuss.channel's strict two-user constraint on chats.
"""
import time

bot = env.ref("mail_bot_odooclaw.odooclaw_bot", raise_if_not_found=False)
admin = env.ref("base.user_admin")
print("BOT:", bot.login, "| partner:", bot.partner_id.id)
print("ADMIN:", admin.login, "| partner:", admin.partner_id.id)

Channel = env["discuss.channel"].sudo().with_user(admin)
ch = Channel.search([
    ("channel_type", "=", "chat"),
    ("channel_member_ids.partner_id", "=", admin.partner_id.id),
    ("channel_member_ids.partner_id", "=", bot.partner_id.id),
], limit=1)
if not ch:
    ch = Channel.create({
        "name": "Chat with OdooClaw",
        "channel_type": "chat",
        "channel_member_ids": [
            (0, 0, {"partner_id": admin.partner_id.id}),
            (0, 0, {"partner_id": bot.partner_id.id}),
        ],
    })
env.cr.commit()
print("CHANNEL:", ch.id, "| members:", ch.channel_member_ids.mapped("partner_id.id"))

question = "¿Cuántos clientes hay en el sistema?"
msg = ch.with_user(admin).message_post(body=question)
env.cr.commit()
print("POSTED:", msg.id, "|", question)

deadline = time.time() + 180
reply = None
while time.time() < deadline:
    env.cr.commit()
    msgs = env["mail.message"].sudo().search([
        ("model", "=", "discuss.channel"),
        ("res_id", "=", ch.id),
        ("author_id", "=", bot.partner_id.id),
    ], order="id desc", limit=1)
    if msgs:
        reply = msgs[0]
        break
    time.sleep(5)

env.cr.commit()
if reply:
    print("REPLY id:", reply.id)
    print("REPLY body:", reply.body)
else:
    print("NO REPLY within timeout")
