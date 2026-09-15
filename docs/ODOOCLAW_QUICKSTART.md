# OdooClaw Doodba Quickstart

This template is prepared for **clone and run** usage without embedded private
credentials.

## 1) Unified setup (recommended)

From repository root:

```bash
scripts/setup-odooclaw-doodba.sh
```

This script executes, in order:

- bootstrap (`scripts/bootstrap-odooclaw.sh`)
- DB/module preparation (`scripts/prepare-odoo-db.sh`)

In interactive mode (default), the script pauses between steps so you can edit and
confirm credentials in `.docker/odoo.env` before DB/module preparation.

This bootstrap step also creates `odooclaw/config/config.json` from
`config.example.json`.

## 2) Manual split (optional)

If you prefer separate steps:

```bash
scripts/bootstrap-odooclaw.sh
scripts/prepare-odoo-db.sh
```

What it runs:

- `invoke git-aggregate`
- `invoke img-build`
- `invoke resetdb`
- `invoke start -d`
- installs `mail_bot_odooclaw` in `devel`

Base module source requirement:

- The module must be present at `odoo/custom/src/private/mail_bot_odooclaw`.
- The installer validates `__manifest__.py` at that location before proceeding.
- If Odoo prints `invalid module names`, setup aborts and asks you to fix addon
  sourcing/paths first.

## 3) Useful options

```bash
scripts/setup-odooclaw-doodba.sh -- --db devel --module mail_bot_odooclaw
scripts/setup-odooclaw-doodba.sh --skip-bootstrap -- --skip-build
scripts/setup-odooclaw-doodba.sh --non-interactive
scripts/prepare-odoo-db.sh --db devel --module mail_bot_odooclaw
scripts/prepare-odoo-db.sh --skip-aggregate --skip-build
scripts/prepare-odoo-db.sh --skip-resetdb
```

## 4) Security and portability

- No API keys are hardcoded in this template.
- Keep secrets only in local `.docker/*.env` files.
- OdooClaw MCP setup uses generic command routing (PATH/module based), avoiding
  environment-specific workspace paths.

## 5) Smoke test (recommended)

After setup, run:

```bash
scripts/smoke-test-odooclaw.sh
```

This validates automatically:

- key containers running (`odoo`, `odooclaw`, `redis`)
- webhook responsiveness
- MCP tools registration line in logs
- base module installed in target database

Useful options:

```bash
scripts/smoke-test-odooclaw.sh --db devel --module mail_bot_odooclaw
scripts/smoke-test-odooclaw.sh --webhook http://127.0.0.1:18790/webhook/odoo
```

## 6) Common module-install issue

If you see `invalid module names, ignored: mail_bot_odooclaw`:

1. Verify folder exists: `odoo/custom/src/private/mail_bot_odooclaw`
2. Verify manifest exists: `odoo/custom/src/private/mail_bot_odooclaw/__manifest__.py`
3. Re-run aggregate/build if needed:

```bash
scripts/setup-odooclaw-doodba.sh --skip-bootstrap -- --skip-resetdb
```

## 7) Common Odoo channel 404 issue

If you see logs like `odoo api error: 404` when OdooClaw sends replies:

1. Ensure `.docker/odoo.env` contains a strict dbfilter matching your DB, for example:

```env
ODOO_DB=devel
ODOO_DBFILTER=^devel$
ODOOCLAW_CHANNELS_ODOO_TARGET_DB=devel
```

2. Restart Odoo and OdooClaw:

```bash
docker compose restart odoo odooclaw
```

The unified setup script now auto-adds both of these if missing:

- `ODOO_DBFILTER=^<ODOO_DB>$`
- `ODOOCLAW_CHANNELS_ODOO_TARGET_DB=<ODOO_DB>`

## 8) Common DNS/proxy issue in development

If you see errors like:

`lookup opencode.ai on 127.0.0.11:53: server misbehaving`

the container is typically running with blocked egress or inherited proxy settings.

Template defaults now disable outbound proxy vars for `odooclaw` in development:

- `HTTP_PROXY=`
- `HTTPS_PROXY=`
- `ALL_PROXY=`
- `NO_PROXY=localhost,127.0.0.1,odoo,redis,db`

and use non-internal default network in `devel.yaml` unless overridden.

After pulling changes, restart stack:

```bash
docker compose restart odooclaw odoo
```

## 9) Odoo credentials and recommended bot user

- Template development defaults use:
  - `ODOO_USERNAME=admin`
  - `ODOO_PASSWORD=admin`
- If you change the Odoo user password (or switch to API key), update `.docker/odoo.env`
  with matching values used by OdooClaw.
- Recommended production pattern: create a dedicated OdooClaw bot user with full
  required permissions, and use that bot user credentials/API key instead of `admin`.
