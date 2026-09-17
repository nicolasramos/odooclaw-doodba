"""Provision the OdooClaw demo accounts: the public `demo` login and the
`admin` password.

WHY THIS EXISTS
    The demo is public. Visitors should be able to open Discuss, talk to
    OdooClaw and browse the sample data, but they must not reach Settings, the
    Apps list, the database manager or anything else administrative. Handing out
    `admin` gives all of that away, and the first visitor who changes the
    password locks everybody else out.

WHAT IT CREATES
    An ordinary Internal User plus the *user* group of each app the demo shows
    (Sales, Invoicing, Purchase, Inventory, Expenses). Internal User alone is
    not enough: every app's root menu is gated on that app's group, so with only
    `base.group_user` the demo user sees Discuss and almost nothing else - which
    looks exactly like "the modules are not installed". The user-level groups
    open the menus and the data without granting configuration rights, and the
    manager variants are asserted absent. The demo is deliberately NOT
    made read-only at the ORM level: the periodic database reset (see
    odoo/demo-reset.sh) already undoes anything a visitor changes, and a
    hand-written ir.rule is easy to get subtly wrong - a mis-scoped rule that
    blocks writes for `base.group_user` would break the demo for everyone,
    including the people doing the demo. Losing data is covered by the reset;
    losing administrative access is covered here.

IT ALSO RESETS THE ADMIN PASSWORD
    The reset restores the database from a template, so a password a visitor
    changed is reverted anyway - but only a template captured AFTER this ran
    carries the intended one. Setting it here as well means the admin password
    is deterministic: the same value every boot and every reset, which is what
    makes it safe to hand out.

WHY VIA `odoo shell` AND NOT RAW SQL
    An Odoo user is not one row: it needs a res.partner, hashed credentials, the
    implied-group expansion and the company links. Writing those by hand in SQL
    is how you get a user who can log in but whose permissions are subtly wrong.
    Going through the ORM yields a user identical to one created in the UI.

IDEMPOTENT
    Safe to run on every boot AND after every reset: it updates the existing
    user rather than creating a duplicate, and re-derives the group list each
    time, so a visitor who grants themselves extra rights loses them at the next
    restart or reset.

Run as:  odoo shell --database=<db> --no-http < odoo/demo_user.py
"""

import os

LOGIN = os.environ.get("DEMO_USER_LOGIN", "demo")
PASSWORD = os.environ.get("DEMO_USER_PASSWORD", "demo")
NAME = os.environ.get("DEMO_USER_NAME", "Demo (invitado)")
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "")

env = env  # noqa: F821 - injected by `odoo shell`
Users = env["res.users"].sudo()

# base.group_user = "Internal User": required by Discuss, carries no admin rights.
internal = env.ref("base.group_user")

# The apps the demo is meant to show. Without these the demo user opens the
# instance and sees only Discuss and a couple of stray menus - the apps are
# installed but every root menu is gated on a group the user does not have, so
# "the modules are not installed" is what it looks like from the outside. These
# are the *user* groups of each app, not the Administrator ones: they grant the
# menus and read access without giving away configuration rights.
#
# Referenced with raise_if_not_found=False because not every install has them:
# a module that is not installed must not break account provisioning.
DEMO_GROUP_XMLIDS = (
    "sales_team.group_sale_salesman",        # Sales
    "account.group_account_invoice",         # Invoicing
    "account.group_account_readonly",        # Accounting read-only features
    "purchase.group_purchase_user",          # Purchase
    "stock.group_stock_user",                # Inventory
    "hr_expense.group_hr_expense_user",      # Expenses
)

# Administrative groups that must never be attached. Kept explicit so a future
# edit to the list above cannot silently widen access.
FORBIDDEN_GROUP_XMLIDS = (
    "base.group_system",                     # Settings
    "base.group_erp_manager",                # Access Rights
    "sales_team.group_sale_manager",
    "account.group_account_manager",
    "purchase.group_purchase_manager",
    "stock.group_stock_manager",
    "hr_expense.group_hr_expense_manager",
)

demo_groups = [internal]
for xid in DEMO_GROUP_XMLIDS:
    group = env.ref(xid, raise_if_not_found=False)
    if group:
        demo_groups.append(group)
    else:
        print(f"[demo-user] note: {xid} not present (module not installed); skipped")

user = Users.with_context(active_test=False).search([("login", "=", LOGIN)], limit=1)
if user:
    user.write({"name": NAME, "active": True})
else:
    user = Users.create({"name": NAME, "login": LOGIN, "password": PASSWORD})

# Re-apply groups and password on every boot. Odoo expands groups during create,
# so the definitive list is set here rather than at creation time.
user.write({"groups_id": [(6, 0, [g.id for g in demo_groups])]})

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
# Also refuse the manager variant of every app group the demo now receives.
# These grant configuration rights on their app (price lists, sequences,
# warehouse setup...) which is exactly what the demo must not hand out.
for xid in FORBIDDEN_GROUP_XMLIDS:
    group = env.ref(xid, raise_if_not_found=False)
    if group:
        must_not_have.append(group)
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

# Reset the admin password too. A public demo means visitors will change it (or
# lock the account out), and the reset restores from a template - so the value
# only survives if it is written before the template is captured AND re-applied
# after every reset. Doing both is what makes it stable enough to hand out.
admin_note = ""
if ADMIN_PASSWORD:
    admin = env.ref("base.user_admin", raise_if_not_found=False)  # noqa: F821
    if admin:
        admin.sudo().write({"password": ADMIN_PASSWORD})
        env.cr.commit()
        admin_note = " | admin password reset"
    else:
        admin_note = " | WARNING: base.user_admin not found"
        print("[demo-user] WARNING: base.user_admin not found; password not reset")

print(
    f"[demo-user] '{LOGIN}' ready: internal user, no administrative groups "
    f"(groups={user.groups_id.mapped('full_name')}){admin_note}"
)
