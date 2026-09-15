#!/bin/bash
# Odoo demo entrypoint wrapper.
#
# Starts Odoo, then makes sure the OdooClaw shared secret is present in the
# database, and keeps Odoo in the foreground.
#
# Why the token is needed:
#   mail_bot_odooclaw's protected endpoints (/odooclaw/call_kw_as_user and
#   /odooclaw/reply) default-deny unless `odooclaw.reply_token` or
#   `odooclaw.allowed_ips` is configured. OdooClaw's odoo-mcp client sends the
#   token in the X-OdooClaw-Token header, so both sides must agree on the same
#   value. Setting it at boot keeps the secret in Coolify's env vars instead of
#   baked into the image.
#
# Ordering: the parameter is written once Odoo has created its schema, so this
# works on a brand-new database too. Odoo is started in the background only for
# that window and is then handed the foreground.

set -e

if [ -n "${ODOOCLAW_REPLY_TOKEN:-}" ]; then
    /entrypoint.sh "$@" &
    ODOO_PID=$!

    echo "[demo-odoo-init] waiting for Odoo schema to set odooclaw.reply_token"
    for _ in $(seq 1 150); do
        if PGPASSWORD="${PGPASSWORD:-odoopassword}" psql -h "${PGHOST:-db}" \
            -U "${PGUSER:-odoo}" -d "${PGDATABASE:-demo}" -tAc \
            "SELECT 1 FROM ir_config_parameter LIMIT 1" >/dev/null 2>&1; then
            PGPASSWORD="${PGPASSWORD:-odoopassword}" psql -h "${PGHOST:-db}" \
                -U "${PGUSER:-odoo}" -d "${PGDATABASE:-demo}" -q -c \
                "INSERT INTO ir_config_parameter (key, value, create_date, write_date, create_uid, write_uid)
                 SELECT 'odooclaw.reply_token', '${ODOOCLAW_REPLY_TOKEN}', now(), now(), 1, 1
                 WHERE NOT EXISTS (SELECT 1 FROM ir_config_parameter WHERE key = 'odooclaw.reply_token');
                 UPDATE ir_config_parameter SET value = '${ODOOCLAW_REPLY_TOKEN}', write_date = now()
                 WHERE key = 'odooclaw.reply_token';" >/dev/null 2>&1 \
                && echo "[demo-odoo-init] odooclaw.reply_token configured" \
                && break
        fi
        sleep 2
    done

    wait "$ODOO_PID"
else
    echo "[demo-odoo-init] ODOOCLAW_REPLY_TOKEN not set; starting Odoo directly"
    exec /entrypoint.sh "$@"
fi
