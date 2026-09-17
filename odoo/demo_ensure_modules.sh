#!/bin/bash
# Install any module from the demo's wanted list that is not installed yet.
#
# WHY THIS IS SEPARATE FROM THE FIRST-BOOT INIT
#   The entrypoint initialises the database once, guarded by "is mail_bot_odooclaw
#   installed?". That guard is what keeps a restart from re-importing every demo
#   dataset on top of live data - but it also means a database created before a
#   module was added to the list would never receive it. So the wanted list is
#   reconciled on every boot and after every reset.
#
# WHY ONLY THE MISSING ONES
#   `--init` on an already-installed module makes Odoo load its demo data again,
#   and re-importing datasets over existing records aborts the registry (the
#   purchase-order-line failure documented in demo-entrypoint.sh). Installing
#   only what is absent avoids that entirely.
#
# Usage: demo_ensure_modules.sh <database> <comma-separated module list>

set -u

DB="${1:?database required}"
WANTED="${2:-}"
[ -n "$WANTED" ] || exit 0

# Always query the target database: ir_module_module lives there, not in the
# `postgres` maintenance database.
PSQL=(psql -h "${PGHOST:-db}" -U "${PGUSER:-odoo}" -d "$DB")
export PGPASSWORD="${PGPASSWORD:-odoopassword}"

log() { echo "[demo-modules] $(date -u '+%Y-%m-%dT%H:%M:%SZ') $*"; }

# Which of the wanted modules are not installed? Asked of ir_module_module so the
# answer reflects what this database actually has, not what the image ships.
MISSING=""
IFS=',' read -r -a modules <<< "$WANTED"
for m in "${modules[@]}"; do
    [ -n "$m" ] || continue
    state="$("${PSQL[@]}" -tAc \
        "SELECT state FROM ir_module_module WHERE name = '$m'" 2>/dev/null | tr -d '[:space:]')"
    if [ "$state" != "installed" ]; then
        MISSING="${MISSING:+$MISSING,}$m"
    fi
done

if [ -z "$MISSING" ]; then
    log "all wanted modules already installed"
    exit 0
fi

log "installing missing modules: $MISSING"

# Run as the Odoo user: it writes into the filestore, and root-owned files there
# would lock the web container out.
run_as_odoo() {
    if [ "$(id -u)" = "0" ] && command -v runuser >/dev/null 2>&1; then
        runuser -u "${ODOO_OS_USER:-odoo}" -- "$@"
    else
        "$@"
    fi
}

if run_as_odoo odoo --database="$DB" --init="$MISSING" --stop-after-init \
        --no-http --db-filter="^$DB\$" 2>&1 | tail -5; then
    log "modules installed: $MISSING"
else
    log "WARNING: module install returned non-zero for: $MISSING"
fi

exit 0
