#!/bin/bash
# OdooClaw demo entrypoint.
#
# Renders ~/.odooclaw/config.json from environment variables, then starts the
# gateway.
#
# Why render the config instead of shipping it:
#   OdooClaw does NOT expand `${VAR}` inside config.json (verified against the
#   binary: a literal `${OPENAI_API_KEY}` is sent to the provider as-is and the
#   request fails with 401). The `providers` block is also unreliable for this -
#   its env tags are templated as `ODOOCLAW_PROVIDERS_{{.Name}}_API_KEY`, which
#   caarlos0/env cannot resolve, so ODOOCLAW_PROVIDERS_OPENAI_API_KEY never
#   reaches cfg.Providers (HasProvidersConfig stays false).
#
#   The only dependable path is a real `model_list` entry with a real api_key.
#   Rendering it here keeps the secret in Coolify's env vars instead of in git.

set -euo pipefail

CONFIG_DIR="${HOME}/.odooclaw"
CONFIG_FILE="${CONFIG_DIR}/config.json"
mkdir -p "${CONFIG_DIR}"

: "${OPENAI_API_KEY:?OPENAI_API_KEY is required}"
: "${OPENAI_API_BASE:?OPENAI_API_BASE is required}"
: "${ODOOCLAW_MODEL:?ODOOCLAW_MODEL is required}"
# Shared secret for the mail_bot_odooclaw protected endpoints. The module
# default-denies /odooclaw/call_kw_as_user and /odooclaw/reply unless a token or
# an IP allowlist is configured, so without this the agent cannot query Odoo
# (tools fail with 401) and its replies are refused.
: "${ODOOCLAW_REPLY_TOKEN:?ODOOCLAW_REPLY_TOKEN is required}"

cat > "${CONFIG_FILE}" <<JSON
{
  "agents": {
    "defaults": {
      "workspace": "${HOME}/.odooclaw/workspace",
      "restrict_to_workspace": true,
      "provider": "openai",
      "model_name": "demo-model",
      "max_tokens": 4096,
      "temperature": 0.2,
      "max_tool_iterations": 50
    }
  },
  "model_list": [
    {
      "model_name": "demo-model",
      "model": "openai/${ODOOCLAW_MODEL}",
      "api_base": "${OPENAI_API_BASE}",
      "api_key": "${OPENAI_API_KEY}"
    }
  ],
  "channels": {
    "odoo": {
      "enabled": true,
      "webhook_host": "0.0.0.0",
      "webhook_port": 18790,
      "webhook_path": "/webhook/odoo",
      "target_db": "${ODOO_DB:-demo}",
      "allow_group_mentions": false
    }
  },
  "tools": {
    "mcp": {
      "enabled": true,
      "servers": {
        "odoo-manager": {
          "enabled": true,
          "command": "python3",
          "args": ["-m", "odoo_mcp.server"],
          "env": {
            "PYTHONUNBUFFERED": "1",
            "ODOOCLAW_REPLY_TOKEN": "${ODOOCLAW_REPLY_TOKEN}"
          }
        }
      }
    }
  },
  "gateway": {
    "host": "0.0.0.0",
    "port": 18790
  }
}
JSON

# The odoo-mcp server reads its connection details from the environment, which
# the MCP manager forwards from this process. Keep them explicit so the demo
# agent can actually query Odoo.
export ODOO_URL="${ODOO_URL:-http://odoo:8069}"
export ODOO_DB="${ODOO_DB:-demo}"
export ODOO_USERNAME="${ODOO_USERNAME:-admin}"
export ODOO_PASSWORD="${ODOO_PASSWORD:-admin}"
export ODOOCLAW_CONFIG="${CONFIG_FILE}"

echo "[demo-entrypoint] OdooClaw demo starting: model=${ODOOCLAW_MODEL} odoo=${ODOO_URL} db=${ODOO_DB}"

exec odooclaw gateway
