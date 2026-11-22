# OdooClaw Evolution

Ledger and hot application of N0/N1 changes for Odoo 18.

## What it does

- `odooclaw.change`: one row per change, with level, kind, payload, snapshot, status and hash.
- `odooclaw.forge`: generates a new addon from a validated template, checks that Odoo sees it,
  installs it hot and uninstalls it.
- `odooclaw.overlay`: runs business logic from a separate host as a validated plan, with shadow,
  active and circuit-breaker modes.
- The generated addon ships manifest, model, views, ACL and a test.
- Applies manual fields, inherited views, server actions and menus.
- Rolls back the change from its logical snapshot.
- Exposes an internal API with `X-OdooClaw-Token`.

## Install on an existing Odoo

1. Copy `odooclaw_evolution` into an addons path directory.
2. Restart Odoo or reload the apps list.
3. Install with `-i odooclaw_evolution` or from Apps.

```bash
odoo -d <database> -i odooclaw_evolution --stop-after-init
```

## Install on Doodba

Doodba mounts `odoo/custom/src/private` as an addons path, so the module is visible when it is
copied there:

```bash
cp -R odooclaw_evolution odoo/custom/src/private/
docker compose run --rm odoo odoo -d <database> -i odooclaw_evolution --stop-after-init
```

If you keep modules in a separate addons repository, declare that repository in
`odoo/custom/src/repos.yaml` and list `odooclaw_evolution` under it in
`odoo/custom/src/addons.yaml`, then rebuild.

In the `odooclaw-doodba` repository the module already lives in
`odoo/custom/src/private/odooclaw_evolution`; build the stack, start it and install the module
against the target database.

## API

Generate a token and store it in `ir.config_parameter`:

```python
env['ir.config_parameter'].sudo().set_param('odooclaw_evolution.api_token', '<token>')
```

Call `POST /odooclaw_evolution/api/change` with the header `X-OdooClaw-Token` and a JSON body:

```json
{
  "jsonrpc": "2.0",
  "method": "call",
  "params": {
    "action": "propose",
    "name": "Add margin field",
    "kind": "field",
    "level": "n1",
    "target_model": "sale.order",
    "payload": {"model": "sale.order", "name": "x_margin", "ttype": "float"}
  }
}
```

## Tests

```bash
odoo -d <test_db> -i odooclaw_evolution --test-enable --test-tags /odooclaw_evolution --stop-after-init
```
