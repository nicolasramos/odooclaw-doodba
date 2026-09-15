#!/usr/bin/env python3
"""Set the environment variables for the OdooClaw demo app and deploy it.

Values that belong to the demo:
  ODOOCLAW_REPLY_TOKEN  - shared secret between the Odoo module and the gateway
                          (module default-denies its protected endpoints)
  OPENAI_API_KEY / OPENAI_API_BASE / ODOOCLAW_MODEL - the LLM endpoint
  PG/ODOO_*             - demo database + Odoo bot credentials
"""
import json
import os
import sys
import urllib.request

API = "https://app.nramos.dev/api/v1"
TOKEN = os.environ["COOLIFY_TOKEN"]
UUID = os.environ["APP_UUID"]

ENVS = {
    # --- Odoo demo database ---
    "ODOO_DB": "demo",
    "PGPASSWORD": "odoopassword",
    "ADMIN_PASSWORD": "admin",
    "ODOO_USERNAME": "admin",
    "ODOO_PASSWORD": "admin",
    # --- LLM (LiteLLM gateway) ---
    "OPENAI_API_KEY": os.environ["OPENAI_API_KEY"],
    "OPENAI_API_BASE": os.environ["OPENAI_API_BASE"],
    "ODOOCLAW_MODEL": os.environ["ODOOCLAW_MODEL"],
    # --- Shared secret for mail_bot_odooclaw protected endpoints ---
    "ODOOCLAW_REPLY_TOKEN": os.environ["ODOOCLAW_REPLY_TOKEN"],
}


def call(method, path, payload=None):
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(
        API + path, data=data, method=method,
        headers={"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            body = r.read().decode()
            return r.status, (json.loads(body) if body.strip() else {})
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read().decode() or "{}")


def main():
    # Existing keys are replaced so re-runs stay consistent.
    status, existing = call("GET", f"/applications/{UUID}/envs")
    by_key = {e["key"]: e for e in (existing if isinstance(existing, list) else [])}

    for key, value in ENVS.items():
        if key in by_key:
            env_uuid = by_key[key]["uuid"]
            st, res = call("PATCH", f"/applications/{UUID}/envs",
                           {"key": key, "value": value, "uuid": env_uuid})
            print(f"update {key}: {st}")
        else:
            st, res = call("POST", f"/applications/{UUID}/envs",
                           {"key": key, "value": value})
            print(f"create {key}: {st} {json.dumps(res)[:120] if st not in (200, 201) else ''}")


if __name__ == "__main__":
    main()
