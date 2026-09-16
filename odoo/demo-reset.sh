#!/bin/bash
# Periodic demo database reset.
#
# WHY THIS EXISTS
#   The demo is public: visitors log in, change the admin password, edit and
#   delete records. Without a reset the demo drifts away from the curated
#   dataset and eventually locks everyone out. This restores the exact demo
#   state on a schedule, so nobody has to do it by hand.
#
# WHAT "RESET" MEANS HERE
#   Drop the public database and recreate it from a pristine template captured
#   at first boot. Everything a visitor did is discarded — records, settings and
#   password changes included — so the demo returns to byte-for-byte its initial
#   state.
#
# WHY A TEMPLATE COPY AND NOT A RE-INIT
#   Re-running `odoo --init` takes minutes and would have to be redone from
#   scratch on every reset. `CREATE DATABASE ... TEMPLATE ...` is a file-level
#   copy: it takes seconds, is deterministic, and preserves the exact
#   initialised state (including the OdooClaw reply token) without touching the
#   module registry. The template is built once, right after the first-boot
#   init, and never modified afterwards.
#
# WHY A SIDECAR AND NOT A LOOP INSIDE THE ODOO CONTAINER
#   Odoo runs the `odoo` binary in the foreground as PID 1. A reset drops and
#   recreates the database underneath the running web process, so it must not be
#   able to take the web process down with it. As its own container the loop can
#   die, restart, or fail loudly while the demo keeps serving.
#
# ENVIRONMENT
#   RESET_INTERVAL_HOURS  Hours between resets. 0 disables the schedule.
#                         Default 24.
#   RESET_ON_START        "true" resets immediately when the stack comes up.
#                         Default false (first boot already initialises).
#   RESET_MAX_ATTEMPTS    Attempts per reset. Default 3.
#   RESET_GRACE_SECONDS   Wait after boot before the first scheduled reset, so a
#                         deploy doesn't reset under someone mid-demo.
#                         Default 300.

set -u

DB="${ODOO_DB:-demo}"
TEMPLATE="${ODOO_DB:-demo}_template"
PGHOST_RES="${PGHOST:-db}"
PGUSER_RES="${PGUSER:-odoo}"
export PGPASSWORD="${PGPASSWORD:-odoopassword}"

INTERVAL_HOURS="${RESET_INTERVAL_HOURS:-24}"
ON_START="${RESET_ON_START:-false}"
MAX_ATTEMPTS="${RESET_MAX_ATTEMPTS:-3}"
GRACE="${RESET_GRACE_SECONDS:-300}"

ADMIN_DB=postgres
PSQL=(psql -h "$PGHOST_RES" -U "$PGUSER_RES" -d "$ADMIN_DB")

# Shared with the Odoo container so the web client can show a live countdown.
# Written atomically (tmp + mv) because Odoo may read it mid-update.
SCHEDULE_FILE="${DEMO_SCHEDULE_FILE:-/shared/demo_schedule.json}"

log() { echo "[demo-reset] $(date -u '+%Y-%m-%dT%H:%M:%SZ') $*"; }

# Drop privileges for anything that runs `odoo`: this sidecar runs as root (it
# needs to own the shared volume), but Odoo must not create root-owned files in
# the filestore or the web container would lose access to them.
as_odoo() {
    if [ "$(id -u)" = "0" ] && command -v runuser >/dev/null 2>&1; then
        runuser -u "${ODOO_OS_USER:-odoo}" -- "$@"
    else
        "$@"
    fi
}

# The shared volume is created by Docker as root. When running as root, hand it
# to the Odoo user so both containers can read the schedule file.
prepare_shared_dir() {
    local dir
    dir="$(dirname "$SCHEDULE_FILE")"
    [ "$(id -u)" = "0" ] || return 0
    mkdir -p "$dir" 2>/dev/null || return 0
    chown -R "${ODOO_OS_USER:-odoo}" "$dir" 2>/dev/null || true
}

# Publish the schedule both containers can see: when the next reset is due, how
# often it runs, and when it last completed.
write_schedule() {
    local next_epoch="$1" last_epoch="$2" status="$3"
    [ -d "$(dirname "$SCHEDULE_FILE")" ] || return 0
    {
        printf '{"next_reset_epoch": %s, "interval_hours": %s, "last_reset_epoch": %s, "status": "%s", "updated_epoch": %s}\n' \
            "${next_epoch:-0}" "$INTERVAL_HOURS" "${last_epoch:-0}" "$status" "$(date +%s)"
    } > "${SCHEDULE_FILE}.tmp" 2>/dev/null && mv "${SCHEDULE_FILE}.tmp" "$SCHEDULE_FILE" 2>/dev/null || true
}

db_ready() { "${PSQL[@]}" -tAc "SELECT 1" >/dev/null 2>&1; }

# Run a statement against the admin database, returning its output. Used where
# the caller needs the error text (stderr is otherwise swallowed by 2>&1 on a
# successful no-op and the real cause is lost).
run_psql() { "${PSQL[@]}" -c "$1"; }

oid() {
    "${PSQL[@]}" -tAc "SELECT 1 FROM pg_database WHERE datname = '$1'" 2>/dev/null | tr -d '[:space:]'
}

wait_for_db() {
    local waited=0
    until db_ready; do
        [ "$waited" -ge 300 ] && { log "FATAL: PostgreSQL unreachable after 300s"; return 1; }
        sleep 5; waited=$((waited + 5))
    done
    return 0
}

# The reset drops the DB under the running web process, so only run it once Odoo
# is actually healthy and able to reconnect. When no health URL is configured the
# check is skipped entirely (useful for tests and single-container runs).
wait_for_odoo_http() {
    local url="${ODOO_HEALTH_URL:-http://odoo:8069/web/health}"
    [ -z "$url" ] && return 0
    local waited=0
    until curl -fsS -m 5 "$url" >/dev/null 2>&1; do
        if [ "$waited" -ge "${ODOO_HEALTH_TIMEOUT:-300}" ]; then
            log "WARNING: Odoo not healthy at $url after ${waited}s; proceeding"
            return 0
        fi
        sleep 5; waited=$((waited + 5))
    done
    return 0
}

terminate_connections() {
    # DROP/CREATE DATABASE fails while any session is connected, and Odoo keeps
    # pooled connections open, so they must be terminated explicitly first.
    "${PSQL[@]}" -tAc "
        SELECT pg_terminate_backend(pid) FROM pg_stat_activity
        WHERE datname = '$1' AND pid <> pg_backend_pid();
    " >/dev/null 2>&1 || true
}

# Create the pristine template, once. Called after the first boot has finished
# initialising the database.
ensure_template() {
    if [ "$(oid "$TEMPLATE")" = "1" ]; then
        return 0
    fi
    if [ "$(oid "$DB")" != "1" ]; then
        log "no template and no database yet; nothing to do"
        return 1
    fi
    log "capturing the pristine template '$TEMPLATE' from '$DB'"
    terminate_connections "$DB"
    sleep 2
    if "${PSQL[@]}" -c "CREATE DATABASE \"$TEMPLATE\" TEMPLATE \"$DB\";" >/dev/null 2>&1; then
        log "template captured"
        return 0
    fi
    log "WARNING: could not capture the template (will fall back to re-init)"
    return 1
}

do_reset() {
    local attempt=1
    while [ "$attempt" -le "$MAX_ATTEMPTS" ]; do
        log "reset attempt $attempt/$MAX_ATTEMPTS ('$DB')"
        wait_for_db || return 1
        wait_for_odoo_http
        terminate_connections "$DB"
        sleep 3

        if [ "$(oid "$TEMPLATE")" = "1" ]; then
            # Fast path: file-level copy of the pristine database.
            #
            # Terminate sessions on the TEMPLATE as well: PostgreSQL refuses
            # CREATE DATABASE ... TEMPLATE while any session is connected to the
            # source ("source database is being accessed by other users"). This
            # bit the first production reset, where the sidecar's own template
            # capture had left a connection behind.
            #
            # Capture stderr: a silent failure here is impossible to diagnose
            # from the container logs, and this runs unattended.
            local err
            terminate_connections "$TEMPLATE"
            sleep 1
            if err="$(run_psql "DROP DATABASE IF EXISTS \"$DB\";" 2>&1)" \
               && err="$(run_psql "CREATE DATABASE \"$DB\" TEMPLATE \"$TEMPLATE\";" 2>&1)"; then
                log "reset completed from template"
                return 0
            fi
            log "WARNING: template reset failed (attempt $attempt): $(echo "$err" | tr '\n' ' ' | cut -c1-300)"
        else
            # Slow fallback: rebuild from scratch. Used only if the template was
            # never captured (e.g. the sidecar started after the DB existed).
            log "no template available; rebuilding '$DB' from scratch"
            if "${PSQL[@]}" -c "DROP DATABASE IF EXISTS \"$DB\";" >/dev/null 2>&1; then
                sleep 3
                # Run as the Odoo user: it writes into the filestore, and
                # root-owned files there would break the web container.
                if as_odoo odoo --database="$DB" \
                        --init="${ODOO_INIT_MODULES:-mail_bot_odooclaw,crm,sale_management,account,purchase,stock,contacts}" \
                        --stop-after-init --no-http >/dev/null 2>&1; then
                    log "reset completed by re-init"
                    ensure_template
                    return 0
                fi
            fi
            log "WARNING: re-init failed (attempt $attempt)"
        fi

        attempt=$((attempt + 1))
        sleep 10
    done
    log "ERROR: reset failed after $MAX_ATTEMPTS attempts; the demo keeps its current data"
    return 1
}

log "starting (interval=${INTERVAL_HOURS}h, on_start=${ON_START}, db=$DB, template=$TEMPLATE)"

# The sidecar runs as root (see compose `user: root`) so it can own the shared
# volume Docker creates root-owned. The file it writes is world-readable, which
# is all the Odoo container needs since it only reads it.
prepare_shared_dir

if [ "$INTERVAL_HOURS" = "0" ]; then
    log "RESET_INTERVAL_HOURS=0 -> automatic reset disabled"
    ensure_template || true
    write_schedule 0 0 "disabled"
    # Stay alive so the container doesn't enter a restart loop.
    while true; do sleep 3600; done
fi

ensure_template || true

if [ "$ON_START" = "true" ]; then
    # A reset already just happened, so the next one is a full interval away -
    # don't also apply the post-boot grace period or it would reset twice.
    if do_reset; then LAST_RESET="$(date +%s)"; else LAST_RESET=0; fi
    FIRST_WAIT="$((INTERVAL_HOURS * 3600))"
else
    LAST_RESET=0
    # First pass waits the grace period so a redeploy doesn't wipe the database
    # under someone mid-demo; afterwards the interval governs.
    FIRST_WAIT="$GRACE"
fi

while true; do
    NEXT_RESET=$(( $(date +%s) + FIRST_WAIT ))
    log "next reset at $(date -u -d "@$NEXT_RESET" '+%Y-%m-%dT%H:%M:%SZ' 2>/dev/null || echo "epoch $NEXT_RESET") (in ${FIRST_WAIT}s)"
    write_schedule "$NEXT_RESET" "$LAST_RESET" "scheduled"
    sleep "$FIRST_WAIT"
    FIRST_WAIT="$((INTERVAL_HOURS * 3600))"

    if do_reset; then
        LAST_RESET="$(date +%s)"
        write_schedule "$(( LAST_RESET + INTERVAL_HOURS * 3600 ))" "$LAST_RESET" "ok"
    else
        # The demo keeps serving; retry at the next interval rather than
        # hammering a database that is not coming back.
        write_schedule "$(( $(date +%s) + INTERVAL_HOURS * 3600 ))" "$LAST_RESET" "failed"
    fi
done
