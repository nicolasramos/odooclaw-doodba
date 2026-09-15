#!/usr/bin/env python3
"""Create the OdooClaw demo application in Coolify (Root Team, project `odooclaw`).

Uses the Coolify v4 API. Mirrors the proven pattern of the existing
`eco-doodba-test` app in the same project/team (public repo, build_pack
dockercompose, docker_compose_location, healthcheck off, autogenerate domain off
until the real hostname is wired).

Idempotent: if an app with the target name already exists, it is reused.
"""
import json
import os
import sys
import urllib.request

API = "https://app.nramos.dev/api/v1"
TOKEN = os.environ["COOLIFY_TOKEN"]
PROJECT_UUID = "gym1tkt4u881d6qtq51gjr8d"       # Root Team / project "odooclaw"
ENVIRONMENT_NAME = "production"
ENVIRONMENT_UUID = "rjpruhwilec1y0en8im4cy4w"
SERVER_UUID = "fkoh5xnl6smxkb605h1yqzm7"        # "localhost" (panel host)
# The localhost server exposes two docker destinations; Coolify requires an
# explicit destination_uuid or the create call fails with
# "Server has multiple destinations and you do not set destination_uuid."
# "coolify" is the one joined by Traefik, so it is the correct target here.
DESTINATION_UUID = "pavx856v9irn3ytjuuxbf1n3"
APP_NAME = "odooclaw-demo"
REPO = "https://github.com/nicolasramos/odooclaw-doodba.git"
BRANCH = "feat/NRA-2807-odooclaw-demo-coolify"
COMPOSE_LOCATION = "/docker-compose.demo.yaml"
DOMAIN = "https://odooclaw.jjgestiones.es"


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
    # Reuse an existing app with the same name (idempotent re-runs).
    _, apps = call("GET", "/applications")
    apps = apps if isinstance(apps, list) else apps.get("data", [])
    for a in apps:
        if a.get("name") == APP_NAME:
            print(f"EXISTS {APP_NAME} uuid={a['uuid']}")
            return a["uuid"]

    payload = {
        "project_uuid": PROJECT_UUID,
        "server_uuid": SERVER_UUID,
        "destination_uuid": DESTINATION_UUID,
        "environment_name": ENVIRONMENT_NAME,
        "environment_uuid": ENVIRONMENT_UUID,
        # Public repo -> no deploy key needed.
        "git_repository": REPO,
        "git_branch": BRANCH,
        "build_pack": "dockercompose",
        "docker_compose_location": COMPOSE_LOCATION,
        "base_directory": "/",
        "name": APP_NAME,
        "description": "OdooClaw demo for clients (NRA-2807)",
        "ports_exposes": "8069",
        # Odoo needs a long first boot (module install), so Coolify's healthcheck
        # would mark it unhealthy before it is ready.
        "health_check_enabled": False,
        # Domain is set explicitly afterwards; avoid an sslip.io fallback host.
        "autogenerate_domain": False,
        "is_auto_deploy_enabled": False,
        "instant_deploy": False,
    }
    status, res = call("POST", "/applications/public", payload)
    if status not in (200, 201) or "uuid" not in res:
        print(f"FAILED status={status} body={json.dumps(res)[:600]}")
        sys.exit(1)

    uuid = res["uuid"]
    print(f"CREATED {APP_NAME} uuid={uuid}")

    # Domain routing for compose apps: map the service name -> public URL.
    status, res = call("PATCH", f"/applications/{uuid}", {
        "docker_compose_domains": [
            {"name": "odoo", "domain": DOMAIN},
        ],
        "fqdn": DOMAIN,
    })
    print(f"domain patch status={status} body={json.dumps(res)[:300]}")
    print(uuid)


if __name__ == "__main__":
    main()
