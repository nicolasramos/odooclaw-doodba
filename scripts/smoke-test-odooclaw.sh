#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DB_NAME="${DB_NAME:-devel}"
MODULE_NAME="${MODULE_NAME:-mail_bot_odooclaw}"
WEBHOOK_URL="${WEBHOOK_URL:-http://127.0.0.1:18790/webhook/odoo}"

PASS_COUNT=0
FAIL_COUNT=0

usage() {
  cat <<'EOF'
Smoke test for OdooClaw + Doodba template.

Usage:
  scripts/smoke-test-odooclaw.sh [options]

Options:
  --db NAME         Database name to verify (default: devel)
  --module NAME     Odoo module to verify (default: mail_bot_odooclaw)
  --webhook URL     Webhook URL to probe (default: http://127.0.0.1:18790/webhook/odoo)
  -h, --help        Show this help
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --db)
      DB_NAME="$2"
      shift 2
      ;;
    --module)
      MODULE_NAME="$2"
      shift 2
      ;;
    --webhook)
      WEBHOOK_URL="$2"
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown option: $1" >&2
      usage
      exit 1
      ;;
  esac
done

if docker compose version >/dev/null 2>&1; then
  DOCKER_COMPOSE=(docker compose)
elif command -v docker-compose >/dev/null 2>&1; then
  DOCKER_COMPOSE=(docker-compose)
else
  echo "ERROR: docker compose is required." >&2
  exit 1
fi

check_pass() {
  local msg="$1"
  PASS_COUNT=$((PASS_COUNT + 1))
  echo "[PASS] $msg"
}

check_fail() {
  local msg="$1"
  FAIL_COUNT=$((FAIL_COUNT + 1))
  echo "[FAIL] $msg"
}

echo "Running smoke test from: $ROOT_DIR"
cd "$ROOT_DIR"

echo "1) Checking key services are running..."
for svc in odoo odooclaw redis; do
  if "${DOCKER_COMPOSE[@]}" ps --status running --services | grep -qx "$svc"; then
    check_pass "Service '$svc' is running"
  else
    check_fail "Service '$svc' is not running"
  fi
done

echo "2) Probing OdooClaw webhook endpoint..."
if command -v curl >/dev/null 2>&1; then
  HTTP_CODE="$(curl -s -o /dev/null -w '%{http_code}' "$WEBHOOK_URL" || true)"
  if [[ "$HTTP_CODE" =~ ^[1-5][0-9][0-9]$ ]] && [[ "$HTTP_CODE" != "000" ]]; then
    check_pass "Webhook responds at $WEBHOOK_URL (HTTP $HTTP_CODE)"
  else
    check_fail "Webhook not reachable at $WEBHOOK_URL"
  fi
else
  check_fail "curl not available to test webhook"
fi

echo "3) Checking MCP registration in odooclaw logs..."
if "${DOCKER_COMPOSE[@]}" logs --no-color odooclaw 2>/dev/null | grep -q "MCP tools registered successfully"; then
  LINE="$("${DOCKER_COMPOSE[@]}" logs --no-color odooclaw 2>/dev/null | grep "MCP tools registered successfully" | tail -n 1)"
  check_pass "MCP registration detected: $LINE"
else
  check_fail "No MCP registration line found in odooclaw logs"
fi

echo "4) Verifying base module installation in Odoo DB..."
if "${DOCKER_COMPOSE[@]}" exec -T odoo odoo shell -d "$DB_NAME" --no-http <<PY >/dev/null 2>&1
module = env['ir.module.module'].search([('name', '=', '$MODULE_NAME')], limit=1)
if not module or module.state != 'installed':
    raise SystemExit(1)
raise SystemExit(0)
PY
then
  check_pass "Module '$MODULE_NAME' is installed in DB '$DB_NAME'"
else
  check_fail "Module '$MODULE_NAME' is not installed in DB '$DB_NAME'"
fi

echo
echo "Smoke test summary: PASS=$PASS_COUNT FAIL=$FAIL_COUNT"
if [[ $FAIL_COUNT -gt 0 ]]; then
  exit 1
fi

exit 0
