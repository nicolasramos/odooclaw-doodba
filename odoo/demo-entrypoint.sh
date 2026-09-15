#!/bin/bash
# Odoo demo entrypoint wrapper.
#
# Responsibilities:
#   1. Initialise the demo database ONCE (Odoo modules + demo data).
#   2. Make sure the OdooClaw shared secret is present in that database.
#   3. Start Odoo normally and keep it in the foreground.
#
# Why init lives here instead of in the compose `command`:
#   a `command: odoo --init=...` re-imports every demo dataset on each restart and
#   redeploy. Re-importing on top of an existing database aborts the registry
#   ("Cannot delete a purchase order line which is in state 'Purchase Order'"),
#   so the app only survived its very first boot. Doing it here means the init
#   runs when the marker table is empty and never again.
#
# Why the token is needed:
#   mail_bot_odooclaw's protected endpoints (/odooclaw/call_kw_as_user and
#   /odooclaw/reply) default-deny unless `odooclaw.reply_token` or
#   `odooclaw.allowed_ips` is configured. OdooClaw's odoo-mcp client sends the
#   token in the X-OdooClaw-Token header, so both sides must agree on the value.

set -e

DB="${PGDATABASE:-demo}"
PSQL=(psql -h "${PGHOST:-db}" -U "${PGUSER:-odoo}" -d "$DB")

db_ready() {
    PGPASSWORD="${PGPASSWORD:-odoopassword}" "${PSQL[@]}" -tAc "SELECT 1" >/dev/null 2>&1
}

schema_ready() {
    PGPASSWORD="${PGPASSWORD:-odoopassword}" "${PSQL[@]}" -tAc \
        "SELECT 1 FROM ir_module_module LIMIT 1" >/dev/null 2>&1
}

echo "[demo-odoo-init] waiting for PostgreSQL at ${PGHOST:-db}"
for _ in $(seq 1 60); do
    db_ready && break
    sleep 2
done

# Initialise only when the OdooClaw bridge is not present yet.
NEEDS_INIT=1
if schema_ready; then
    INSTALLED=$(PGPASSWORD="${PGPASSWORD:-odoopassword}" "${PSQL[@]}" -tAc \
        "SELECT state FROM ir_module_module WHERE name = 'mail_bot_odooclaw'" 2>/dev/null | tr -d '[:space:]')
    [ "$INSTALLED" = "installed" ] && NEEDS_INIT=0
fi

if [ "$NEEDS_INIT" = "1" ]; then
    echo "[demo-odoo-init] initialising the demo database (modules + demo data)"
    odoo --database="$DB" \
         --init=mail_bot_odooclaw,crm,sale_management,account,purchase,stock,contacts \
         --stop-after-init \
         --db-filter="^$DB\$" &
    INIT_PID=$!
    wait "$INIT_PID" || echo "[demo-odoo-init] init exited non-zero; continuing"
    echo "[demo-odoo-init] init finished"
fi

if [ -n "${ODOOCLAW_REPLY_TOKEN:-}" ]; then
    for _ in $(seq 1 150); do
        if schema_ready; then
            PGPASSWORD="${PGPASSWORD:-odoopassword}" "${PSQL[@]}" -q -c \
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
fi

# Normal runtime: hand off to the official entrypoint (db args + wait-for-psql).
exec /entrypoint.sh "$@"
