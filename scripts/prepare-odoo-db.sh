#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DB_NAME="${DB_NAME:-devel}"
MODULE_NAME="${MODULE_NAME:-mail_bot_odooclaw}"
RUN_AGGREGATE=true
RUN_BUILD=true
RUN_RESETDB=true
INTERACTIVE=true
PRIVATE_ADDONS_DIR="odoo/custom/src/private"

usage() {
  cat <<'EOF'
Prepare Doodba DB and install base OdooClaw module.

Usage:
  scripts/prepare-odoo-db.sh [options]

Options:
  --db NAME              Target database (default: devel)
  --module NAME          Odoo module to install (default: mail_bot_odooclaw)
  --skip-aggregate       Skip `invoke git-aggregate`
  --skip-build           Skip `invoke img-build`
  --skip-resetdb         Skip `invoke resetdb`
  --non-interactive      Disable prompts and use safe defaults
  -h, --help             Show this help

Environment overrides:
  DB_NAME, MODULE_NAME
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
    --skip-aggregate)
      RUN_AGGREGATE=false
      shift
      ;;
    --skip-build)
      RUN_BUILD=false
      shift
      ;;
    --skip-resetdb)
      RUN_RESETDB=false
      shift
      ;;
    --non-interactive)
      INTERACTIVE=false
      shift
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

confirm_step() {
  local message="$1"
  if [[ "$INTERACTIVE" != true ]]; then
    return 1
  fi

  local answer=""
  local answer_normalized=""
  while true; do
    read -r -p "$message [y/N]: " answer
    answer_normalized="$(printf '%s' "$answer" | tr '[:upper:]' '[:lower:]')"
    case "$answer_normalized" in
      y|yes)
        return 0
        ;;
      n|no|"")
        return 1
        ;;
      *)
        echo "Please answer 'y' or 'n'."
        ;;
    esac
  done
}

if ! command -v invoke >/dev/null 2>&1; then
  echo "ERROR: invoke is required. Install it first (pip install invoke)." >&2
  exit 1
fi

cd "$ROOT_DIR"

MODULE_SOURCE_DIR="$PRIVATE_ADDONS_DIR/$MODULE_NAME"
MODULE_MANIFEST="$MODULE_SOURCE_DIR/__manifest__.py"

echo "[sanity] Validating module source location"
if [[ ! -f "$MODULE_MANIFEST" ]]; then
  echo "ERROR: Required module manifest not found: $MODULE_MANIFEST" >&2
  echo "Expected location: /odoo/custom/src/private/$MODULE_NAME" >&2
  echo "Please ensure the module is present under private addons before continuing." >&2
  exit 1
fi
echo "[sanity] OK: module source found at $MODULE_SOURCE_DIR"

if docker compose version >/dev/null 2>&1; then
  DOCKER_COMPOSE=(docker compose)
elif command -v docker-compose >/dev/null 2>&1; then
  DOCKER_COMPOSE=(docker-compose)
else
  echo "ERROR: docker compose is required." >&2
  exit 1
fi

ENTRYPOINT_DIR="odoo/custom/entrypoint.d"
if [[ -f "$ENTRYPOINT_DIR/.empty" ]]; then
  echo "[sanity] Removing non-executable placeholder: $ENTRYPOINT_DIR/.empty"
  rm -f "$ENTRYPOINT_DIR/.empty"
fi

echo "[1/5] Updating addon sources (git-aggregate)"
if [[ "$RUN_AGGREGATE" == true ]]; then
  invoke git-aggregate
else
  echo "  Skipped."
fi

echo "[2/5] Building Odoo image (img-build)"
if [[ "$RUN_BUILD" == true ]]; then
  invoke img-build
else
  echo "  Skipped."
fi

echo "[3/5] Preparing database ($DB_NAME)"
if [[ "$RUN_RESETDB" == true ]]; then
  RESETDB_LOG="$(mktemp)"
  if ! invoke resetdb >"$RESETDB_LOG" 2>&1; then
    cat "$RESETDB_LOG"
    if grep -q "Database already exists" "$RESETDB_LOG"; then
      echo "WARNING: Database '$DB_NAME' already exists."
      if confirm_step "Continue by reusing existing database and skipping resetdb?"; then
        echo "  Reusing existing database."
      else
        echo "ERROR: resetdb failed due to existing database." >&2
        echo "Tip: run with --skip-resetdb if you want to reuse the DB." >&2
        rm -f "$RESETDB_LOG"
        exit 1
      fi
    else
      rm -f "$RESETDB_LOG"
      echo "ERROR: resetdb failed." >&2
      exit 1
    fi
  fi
  rm -f "$RESETDB_LOG"
else
  echo "  Skipped."
fi

echo "[4/5] Starting stack"
invoke start -d

echo "[5/5] Installing base module: $MODULE_NAME"
INSTALL_LOG="$(mktemp)"
if ! "${DOCKER_COMPOSE[@]}" exec -T odoo \
  odoo -d "$DB_NAME" -i "$MODULE_NAME" --without-demo=all --stop-after-init \
  >"$INSTALL_LOG" 2>&1; then
  cat "$INSTALL_LOG"
  rm -f "$INSTALL_LOG"
  echo "ERROR: Odoo module installation command failed." >&2
  exit 1
fi

if grep -qi "invalid module names" "$INSTALL_LOG"; then
  cat "$INSTALL_LOG"
  rm -f "$INSTALL_LOG"
  echo "ERROR: Odoo reported invalid module names for '$MODULE_NAME'." >&2
  echo "Verify the module exists in $MODULE_SOURCE_DIR and is included by Doodba addons paths." >&2
  exit 1
fi

if ! "${DOCKER_COMPOSE[@]}" exec -T odoo odoo shell -d "$DB_NAME" --no-http <<PY >/dev/null 2>&1
module = env['ir.module.module'].search([('name', '=', '$MODULE_NAME')], limit=1)
if not module or module.state != 'installed':
    raise SystemExit(1)
raise SystemExit(0)
PY
then
  cat "$INSTALL_LOG"
  rm -f "$INSTALL_LOG"
  echo "ERROR: Module '$MODULE_NAME' is not in installed state after installation." >&2
  exit 1
fi
rm -f "$INSTALL_LOG"

echo "Done. Restarting Odoo service..."
"${DOCKER_COMPOSE[@]}" restart odoo

echo "OdooClaw base module installed in database '$DB_NAME'."
