"""Create (or refresh) the non-administrative demo login for the OdooClaw demo.

WHY THIS EXISTS
    The demo is public. Visitors should be able to open Discuss, talk to
    OdooClaw and browse the sample data, but they must not reach Settings, the
    Apps list, the database manager or anything else administrative. Handing out
    `admin` gives all of that away, and the first visitor who changes the
    password locks everybody else out.

WHAT IT CREATES
    An ordinary Internal User (`base.group_user`) and nothing else. That is the
    minimum Odoo needs for Discuss, which is the whole point of the demo, and it
    carries no Settings, Apps or admin rights. The demo is deliberately NOT
    made read-only at the ORM level: the periodic database reset (see
    odoo/demo-reset.sh) already undoes anything a visitor changes, and a
    hand-written ir.rule is easy to get subtly wrong - a mis-scoped rule that
    blocks writes for `base.group_user` would break the demo for everyone,
    including the people doing the demo. Losing data is covered by the reset;
    losing administrative access is covered here.

WHY VIA `odoo shell` AND NOT RAW SQL
    An Odoo user is not one row: it needs a res.partner, hashed credentials, the
    implied-group expansion and the company links. Writing those by hand in SQL
    is how you get a user who can log in but whose permissions are subtly wrong.
    Going through the ORM yields a user identical to one created in the UI.

IDEMPOTENT
    Safe to run on every boot: it updates the existing user rather than creating
    a duplicate, and re-derives the group list each time, so a visitor who grants
    themselves extra rights loses them at the next restart.

Run as:  odoo shell --database=<db> --no-http < odoo/demo_user.py
"""

import os

LOGIN = os.environ.get("DEMO_USER_LOGIN", "demo")
PASSWORD = os.environ.get("DEMO_USER_PASSWORD", "demo")
NAME = os.environ.get("DEMO_USER_NAME", "Demo (invitado)")

env = env  # noqa: F821 - injected by `odoo shell`
Users = env["res.users"].sudo()

# base.group_user = "Internal User": required by Discuss, carries no admin rights.
# Deliberately the ONLY group.
internal = env.ref("base.group_user")

user = Users.with_context(active_test=False).search([("login", "=", LOGIN)], limit=1)
if user:
    user.write({"name": NAME, "active": True})
else:
    user = Users.create({"name": NAME, "login": LOGIN, "password": PASSWORD})

# Re-apply groups and password on every boot. Odoo expands groups during create,
# so the definitive list is set here rather than at creation time.
user.write({"groups_id": [(6, 0, [internal.id])]})

try:
    user.write({"password": PASSWORD})
except Exception as exc:  # noqa: BLE001 - surfaced to the log, not swallowed
    # A password policy module can reject short passwords. Say so plainly rather
    # than leaving a demo account whose password silently is not what was set.
    print(f"[demo-user] WARNING: could not set password {PASSWORD!r}: {exc}")
    raise

if "signup_type" in user._fields:
    user.write({"signup_type": False})

user.partner_id.write({"name": NAME, "active": True})

# Sanity-check the result rather than trusting the writes above. These are the
# properties the demo actually depends on, verified against Odoo 18:
#
#   * no administrative group at all - in particular NOT base.group_system
#     (Settings) and NOT base.group_erp_manager (Access Rights). Either would let
#     a visitor into the administrative side, which is the whole point of giving
#     them a separate account.
#   * still an internal user, because a portal user cannot use the Discuss bot
#     channel and the demo would be dead.
#
# Note that `base.group_user` structurally implies `base.group_no_one`
# ("Technical Features", declared in base/security/base_groups.xml). That is not
# removable - Odoo re-adds it - and it grants no administrative access on its
# own, so it is expected here rather than treated as a leak.
required = env.ref("base.group_user")
must_not_have = [
    env.ref("base.group_system"),       # Settings
    env.ref("base.group_erp_manager"),  # Access Rights
]
for group in must_not_have:
    assert not user.has_group(group.id), (
        f"[demo-user] {LOGIN} has the administrative group "
        f"{group.full_name!r}; visitors would reach the admin side"
    )
assert user.has_group(required.id), (
    f"[demo-user] {LOGIN} is not an internal user; Discuss (the demo's whole "
    f"purpose) would not work"
)

env.cr.commit()
print(
    f"[demo-user] '{LOGIN}' ready: internal user, no administrative groups "
    f"(groups={user.groups_id.mapped('full_name')})"
)
