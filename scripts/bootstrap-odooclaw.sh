#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CONFIG_EXAMPLE="$ROOT_DIR/odooclaw/config/config.example.json"
CONFIG_TARGET="$ROOT_DIR/odooclaw/config/config.json"
ODOO_ENV_SAMPLE="$ROOT_DIR/.docker/odoo_env.sample"
ODOO_ENV_TARGET="$ROOT_DIR/.docker/odoo.env"

echo "Bootstrapping OdooClaw template..."

if [[ ! -f "$CONFIG_EXAMPLE" ]]; then
  echo "ERROR: Missing $CONFIG_EXAMPLE" >&2
  exit 1
fi

if [[ ! -f "$CONFIG_TARGET" ]]; then
  cp "$CONFIG_EXAMPLE" "$CONFIG_TARGET"
  echo "Created odooclaw/config/config.json from config.example.json"
else
  echo "config.json already exists, keeping current file"
fi

if [[ ! -f "$ODOO_ENV_SAMPLE" ]]; then
  echo "ERROR: Missing $ODOO_ENV_SAMPLE" >&2
  exit 1
fi

if [[ ! -f "$ODOO_ENV_TARGET" ]]; then
  cp "$ODOO_ENV_SAMPLE" "$ODOO_ENV_TARGET"
  echo "Created .docker/odoo.env from odoo_env.sample"
else
  echo ".docker/odoo.env already exists, keeping current file"
fi

echo "Bootstrap completed."
echo "Next steps:"
echo "  1) Edit .docker/odoo.env with your API keys"
echo "  2) Run scripts/prepare-odoo-db.sh"
