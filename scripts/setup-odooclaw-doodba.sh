#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RUN_BOOTSTRAP=true
RUN_PREPARE=true
INTERACTIVE=true
ENV_FILE="$ROOT_DIR/.docker/odoo.env"
CONFIGURE_PROVIDER=true

usage() {
  cat <<'EOF'
Unified OdooClaw + Doodba setup orchestrator.

Usage:
  scripts/setup-odooclaw-doodba.sh [options] [-- prepare-options]

Options:
  --skip-bootstrap      Skip bootstrap script
  --skip-prepare        Skip DB/module preparation script
  --skip-provider-setup Skip interactive provider/model setup
  --non-interactive     Disable prompts and continue automatically
  -h, --help            Show this help

Pass-through to prepare script:
  Use -- and then any option supported by scripts/prepare-odoo-db.sh

Examples:
  scripts/setup-odooclaw-doodba.sh
  scripts/setup-odooclaw-doodba.sh -- --db devel --module mail_bot_odooclaw
  scripts/setup-odooclaw-doodba.sh --skip-bootstrap -- --skip-build
EOF
}

ensure_cmd() {
  local cmd="$1"
  if ! command -v "$cmd" >/dev/null 2>&1; then
    echo "ERROR: required command not found: $cmd" >&2
    exit 1
  fi
}

run_prereqs_check() {
  echo "[preflight] Checking prerequisites..."
  ensure_cmd bash
  ensure_cmd git
  ensure_cmd docker
  ensure_cmd invoke

  if ! docker compose version >/dev/null 2>&1 && ! command -v docker-compose >/dev/null 2>&1; then
    echo "ERROR: docker compose is required (plugin or standalone)." >&2
    exit 1
  fi

  if [[ ! -f "$ROOT_DIR/devel.yaml" && ! -f "$ROOT_DIR/prod.yaml" && ! -f "$ROOT_DIR/docker-compose.yml" ]]; then
    echo "ERROR: this does not look like a Doodba project root (no compose files found)." >&2
    exit 1
  fi

  echo "[preflight] OK"
}

confirm_step() {
  local message="$1"
  if [[ "$INTERACTIVE" != true ]]; then
    return 0
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

show_env_hint() {
  cat <<EOF

Before DB/module preparation, verify your credentials in:
  $ENV_FILE

Minimum recommended variables:
  - ODOO_PASSWORD
  - ODOO_DBFILTER (recommended: ^<db_name>$, for example ^devel$)
  - OPENAI_API_KEY
  - ODOOCLAW_AGENTS_DEFAULTS_MODEL_NAME
  - STT_PROVIDER (and STT_* vars when using external STT)

Required module source for base install:
  - odoo/custom/src/private/mail_bot_odooclaw
EOF
}

ensure_odoo_dbfilter() {
  if [[ ! -f "$ENV_FILE" ]]; then
    return 0
  fi

  local db_name=""
  local dbfilter=""
  db_name="$(get_env_value "$ENV_FILE" "ODOO_DB")"
  dbfilter="$(get_env_value "$ENV_FILE" "ODOO_DBFILTER")"

  if [[ -z "$db_name" ]]; then
    db_name="devel"
    set_env_var "$ENV_FILE" "ODOO_DB" "$db_name"
    echo "[env] ODOO_DB was missing. Set to '$db_name'."
  fi

  if [[ -z "$dbfilter" ]]; then
    set_env_var "$ENV_FILE" "ODOO_DBFILTER" "^${db_name}$"
    echo "[env] Added ODOO_DBFILTER=^${db_name}$ to avoid Odoo route 404 with multiple databases."
  else
    echo "[env] ODOO_DBFILTER already set: $dbfilter"
  fi

  local target_db=""
  target_db="$(get_env_value "$ENV_FILE" "ODOOCLAW_CHANNELS_ODOO_TARGET_DB")"
  if [[ -z "$target_db" ]]; then
    set_env_var "$ENV_FILE" "ODOOCLAW_CHANNELS_ODOO_TARGET_DB" "$db_name"
    echo "[env] Added ODOOCLAW_CHANNELS_ODOO_TARGET_DB=$db_name for deterministic multi-DB routing."
  else
    echo "[env] ODOOCLAW_CHANNELS_ODOO_TARGET_DB already set: $target_db"
  fi
}

get_env_value() {
  local file="$1"
  local key="$2"
  awk -F'=' -v k="$key" '
    $0 ~ "^[[:space:]]*" k "=" {
      v = substr($0, index($0, "=") + 1)
      gsub(/^[[:space:]]+|[[:space:]]+$/, "", v)
      print v
      exit
    }
  ' "$file"
}

sync_and_validate_config_model() {
  local config_file="$ROOT_DIR/odooclaw/config/config.json"
  if [[ ! -f "$config_file" ]]; then
    echo "ERROR: Missing config file: $config_file" >&2
    return 1
  fi

  local env_model=""
  local env_provider=""
  local env_openai_base=""
  local env_openai_key=""
  local env_ollama_base=""
  local env_anthropic_key=""

  if [[ -f "$ENV_FILE" ]]; then
    env_model="$(get_env_value "$ENV_FILE" "ODOOCLAW_AGENTS_DEFAULTS_MODEL_NAME")"
    env_provider="$(get_env_value "$ENV_FILE" "ODOOCLAW_PROVIDERS_DEFAULT")"
    env_openai_base="$(get_env_value "$ENV_FILE" "OPENAI_API_BASE")"
    env_openai_key="$(get_env_value "$ENV_FILE" "OPENAI_API_KEY")"
    env_ollama_base="$(get_env_value "$ENV_FILE" "ODOOCLAW_PROVIDERS_OLLAMA_BASE_URL")"
    env_anthropic_key="$(get_env_value "$ENV_FILE" "ANTHROPIC_API_KEY")"
  fi

  python3 - "$config_file" "$env_model" "$env_provider" "$env_openai_base" "$env_openai_key" "$env_ollama_base" "$env_anthropic_key" <<'PY'
import json
import sys

config_path = sys.argv[1]
env_model = (sys.argv[2] or "").strip()
env_provider = (sys.argv[3] or "openai").strip().lower() or "openai"
env_openai_base = (sys.argv[4] or "").strip()
env_openai_key = (sys.argv[5] or "").strip()
env_ollama_base = (sys.argv[6] or "").strip()
env_anthropic_key = (sys.argv[7] or "").strip()

with open(config_path, "r", encoding="utf-8") as f:
    cfg = json.load(f)

tools = cfg.setdefault("tools", {})
mcp = tools.setdefault("mcp", {})
if not bool(mcp.get("enabled", False)):
    mcp["enabled"] = True
    print("[config] Enabled tools.mcp globally (enabled=true)")

agents = cfg.setdefault("agents", {})
defaults = agents.setdefault("defaults", {})
model_list = cfg.setdefault("model_list", [])

target_model = env_model or str(defaults.get("model_name") or "").strip()
if not target_model:
    print("ERROR: model_name is empty in both .docker/odoo.env and config.json", file=sys.stderr)
    sys.exit(1)

defaults["model_name"] = target_model

provider = env_provider if env_provider in {"openai", "ollama", "anthropic"} else "openai"

found = None
for item in model_list:
    if isinstance(item, dict) and str(item.get("model_name", "")).strip() == target_model:
        found = item
        break

if found is None:
    if provider == "ollama":
        new_item = {
            "model_name": target_model,
            "model": f"ollama/{target_model}",
            "api_base": env_ollama_base or "http://host.docker.internal:11434/v1",
        }
    elif provider == "anthropic":
        new_item = {
            "model_name": target_model,
            "model": f"anthropic/{target_model}",
            "api_key": env_anthropic_key or "${ANTHROPIC_API_KEY}",
            "api_base": "https://api.anthropic.com/v1",
        }
    else:
        new_item = {
            "model_name": target_model,
            "model": f"openai/{target_model}",
            "api_key": env_openai_key or "${OPENAI_API_KEY}",
            "api_base": env_openai_base or "https://api.openai.com/v1",
        }
    model_list.append(new_item)
    print(f"[config] Added model_list entry: {new_item['model']}")
else:
    expected_model = f"{provider}/{target_model}"
    if str(found.get("model", "")).strip() != expected_model:
        found["model"] = expected_model
        print(f"[config] Normalized model field to: {expected_model}")

# Keep first model_list entry synced as active default model
if not model_list:
    model_list.append({})

first = model_list[0]
if not isinstance(first, dict):
    first = {}
    model_list[0] = first

first["model_name"] = target_model
first["model"] = f"{provider}/{target_model}"

if provider == "openai":
    first["api_key"] = env_openai_key or "${OPENAI_API_KEY}"
    first["api_base"] = env_openai_base or "${OPENAI_API_BASE}"
elif provider == "ollama":
    first.pop("api_key", None)
    first["api_base"] = env_ollama_base or "http://host.docker.internal:11434/v1"
elif provider == "anthropic":
    first["api_key"] = env_anthropic_key or "${ANTHROPIC_API_KEY}"
    first["api_base"] = "https://api.anthropic.com/v1"

print(f"[config] Synced first model_list entry to: {first['model']}")

with open(config_path, "w", encoding="utf-8") as f:
    json.dump(cfg, f, indent=2, ensure_ascii=False)
    f.write("\n")

print(f"[config] agents.defaults.model_name = {target_model}")
PY
}

set_env_var() {
  local file="$1"
  local key="$2"
  local value="$3"
  local tmp_file
  tmp_file="$(mktemp)"

  awk -v target_key="$key" -v target_value="$value" '
    BEGIN { done=0 }
    $0 ~ "^" target_key "=" {
      print target_key "=" target_value
      done=1
      next
    }
    { print }
    END {
      if (!done) {
        print target_key "=" target_value
      }
    }
  ' "$file" > "$tmp_file"

  mv "$tmp_file" "$file"
}

prompt_required() {
  local label="$1"
  local value=""
  while true; do
    read -r -p "$label: " value
    if [[ -n "$value" ]]; then
      printf '%s' "$value"
      return 0
    fi
    echo "This value is required."
  done
}

prompt_default() {
  local label="$1"
  local default_value="$2"
  local value=""
  read -r -p "$label [$default_value]: " value
  if [[ -z "$value" ]]; then
    printf '%s' "$default_value"
  else
    printf '%s' "$value"
  fi
}

configure_provider_interactive() {
  if [[ "$INTERACTIVE" != true || "$CONFIGURE_PROVIDER" != true ]]; then
    return 0
  fi
  if [[ ! -f "$ENV_FILE" ]]; then
    return 0
  fi

  echo
  echo "Provider/model setup"
  echo "  1) OpenAI"
  echo "  2) OpenAI-compatible"
  echo "  3) Ollama"
  echo "  4) Anthropic"
  echo "  5) Skip (manual)"

  local option=""
  while true; do
    read -r -p "Choose provider [1-5]: " option
    case "$option" in
      1|2|3|4|5) break ;;
      *) echo "Please choose a valid option (1-5)." ;;
    esac
  done

  local model=""
  local api_key=""
  local api_base=""

  case "$option" in
    1)
      model="$(prompt_default "Model name" "gpt-4o-mini")"
      api_key="$(prompt_required "OPENAI_API_KEY")"
      set_env_var "$ENV_FILE" "ODOOCLAW_PROVIDERS_DEFAULT" "openai"
      set_env_var "$ENV_FILE" "OPENAI_API_BASE" "https://api.openai.com/v1"
      set_env_var "$ENV_FILE" "OPENAI_API_KEY" "$api_key"
      set_env_var "$ENV_FILE" "ODOOCLAW_AGENTS_DEFAULTS_MODEL_NAME" "$model"
      ;;
    2)
      model="$(prompt_required "Model name")"
      api_base="$(prompt_required "OPENAI_API_BASE")"
      api_key="$(prompt_required "OPENAI_API_KEY")"
      set_env_var "$ENV_FILE" "ODOOCLAW_PROVIDERS_DEFAULT" "openai"
      set_env_var "$ENV_FILE" "OPENAI_API_BASE" "$api_base"
      set_env_var "$ENV_FILE" "OPENAI_API_KEY" "$api_key"
      set_env_var "$ENV_FILE" "ODOOCLAW_AGENTS_DEFAULTS_MODEL_NAME" "$model"
      ;;
    3)
      model="$(prompt_default "Model name" "llama3.1:8b")"
      api_base="$(prompt_default "ODOOCLAW_PROVIDERS_OLLAMA_BASE_URL" "http://host.docker.internal:11434")"
      set_env_var "$ENV_FILE" "ODOOCLAW_PROVIDERS_DEFAULT" "ollama"
      set_env_var "$ENV_FILE" "ODOOCLAW_PROVIDERS_OLLAMA_BASE_URL" "$api_base"
      set_env_var "$ENV_FILE" "ODOOCLAW_AGENTS_DEFAULTS_MODEL_NAME" "$model"
      ;;
    4)
      model="$(prompt_default "Model name" "claude-3-5-sonnet-latest")"
      api_key="$(prompt_required "ANTHROPIC_API_KEY")"
      set_env_var "$ENV_FILE" "ODOOCLAW_PROVIDERS_DEFAULT" "anthropic"
      set_env_var "$ENV_FILE" "ANTHROPIC_API_KEY" "$api_key"
      set_env_var "$ENV_FILE" "ODOOCLAW_AGENTS_DEFAULTS_MODEL_NAME" "$model"
      ;;
    5)
      echo "Skipping provider setup. Keep manual configuration in $ENV_FILE"
      ;;
  esac
}

PREPARE_ARGS=()
while [[ $# -gt 0 ]]; do
  case "$1" in
    --skip-bootstrap)
      RUN_BOOTSTRAP=false
      shift
      ;;
    --skip-prepare)
      RUN_PREPARE=false
      shift
      ;;
    --non-interactive)
      INTERACTIVE=false
      shift
      ;;
    --skip-provider-setup)
      CONFIGURE_PROVIDER=false
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    --)
      shift
      PREPARE_ARGS=("$@")
      break
      ;;
    *)
      echo "Unknown option: $1" >&2
      usage
      exit 1
      ;;
  esac
done

run_prereqs_check

if [[ "$RUN_BOOTSTRAP" == true ]]; then
  echo "[1/2] Running bootstrap..."
  "$ROOT_DIR/scripts/bootstrap-odooclaw.sh"
else
  echo "[1/2] Bootstrap skipped"
fi

if [[ "$RUN_PREPARE" == true ]]; then
  configure_provider_interactive
fi

ensure_odoo_dbfilter

echo "[config] Syncing model_name and model_list..."
sync_and_validate_config_model

if [[ "$RUN_PREPARE" == true ]]; then
  if [[ -f "$ENV_FILE" ]]; then
    show_env_hint
    if ! confirm_step "Continue with DB/module preparation now?"; then
      echo "Setup paused before DB/module preparation."
      echo "After editing credentials, run:"
      echo "  scripts/setup-odooclaw-doodba.sh --skip-bootstrap"
      exit 0
    fi
  else
    echo "WARNING: env file not found at $ENV_FILE"
    if ! confirm_step "Continue anyway?"; then
      echo "Setup cancelled."
      exit 1
    fi
  fi

  echo "[2/2] Running DB/module preparation..."
  if [[ ${#PREPARE_ARGS[@]} -gt 0 ]]; then
    "$ROOT_DIR/scripts/prepare-odoo-db.sh" "${PREPARE_ARGS[@]}"
  else
    "$ROOT_DIR/scripts/prepare-odoo-db.sh"
  fi
else
  echo "[2/2] DB/module preparation skipped"
fi

echo "Setup flow completed successfully."
