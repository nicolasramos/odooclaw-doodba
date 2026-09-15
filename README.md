[![Doodba deployment](https://img.shields.io/badge/deployment-doodba-informational)](https://github.com/Tecnativa/doodba)
[![Last template update](https://img.shields.io/badge/last%20template%20update-v9.4.1-informational)](https://github.com/Tecnativa/doodba-copier-template/tree/v9.4.1)
[![Odoo](https://img.shields.io/badge/odoo-v18.0-a3478a)](https://github.com/odoo/odoo/tree/18.0)
[![MIT license](https://img.shields.io/badge/license-MIT-success})](LICENSE)
[![pre-commit](https://img.shields.io/badge/pre--commit-enabled-brightgreen?logo=pre-commit&logoColor=white)](https://pre-commit.com/)

# odooclaw-odoo - a Doodba deployment

This repository is a Doodba template prepared to run Odoo + OdooClaw with safe defaults.

## Goals

- Clone and bootstrap quickly.
- No private API keys/tokens embedded in tracked files.
- Keep Doodba daily workflow (`git-aggregate`, `img-build`, `resetdb`, `start`).

## Quick start

1. Clone this repository.
2. Run the unified setup flow:

```bash
scripts/setup-odooclaw-doodba.sh
```

3. The script will pause before DB preparation so you can confirm/edit credentials in
   `.docker/odoo.env`.
4. Run smoke checks:

```bash
scripts/smoke-test-odooclaw.sh
```

Non-interactive CI/automation mode:

```bash
scripts/setup-odooclaw-doodba.sh --non-interactive
```

5. Re-run only DB/module phase when needed:

```bash
scripts/setup-odooclaw-doodba.sh --skip-bootstrap -- --skip-aggregate --skip-build
```

Module source requirement:

- `mail_bot_odooclaw` must exist at `odoo/custom/src/private/mail_bot_odooclaw`.
- Setup now fails fast if that path/manifest is missing or if Odoo reports invalid
  module names.

Odoo user credentials for OdooClaw:

- Default template values are `ODOO_USERNAME=admin` and `ODOO_PASSWORD=admin`
  (development baseline).
- If you change the Odoo user or password/API key, you must update `.docker/odoo.env`
  accordingly.
- Recommended for real deployments: create a dedicated OdooClaw bot user with the
  required permissions and use that user credentials (or API key) instead of admin.

See full instructions in:

- `docs/ODOOCLAW_QUICKSTART.md`

## Keeping upstreams updated

- Doodba scaffold: run `copier update`.
- OdooClaw core: run `scripts/update-odooclaw-core.sh`.

See `docs/ODOOCLAW_CORE_UPDATES.md` for the full workflow and the project-specific files
that must be preserved.

## Upstream references

This project is based on Doodba scaffolding. Check upstream docs:

- [General Doodba docs](https://github.com/Tecnativa/doodba).
- [Doodba copier template docs](https://github.com/Tecnativa/doodba-copier-template)
- [Doodba QA docs](https://github.com/Tecnativa/doodba-qa)

## Credits

This project is maintained by: OdooClaw
