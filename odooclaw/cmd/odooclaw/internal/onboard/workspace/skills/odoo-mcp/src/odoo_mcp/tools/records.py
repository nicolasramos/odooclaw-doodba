from typing import Any

from odoo_mcp.core.client import OdooClient
from odoo_mcp.core.domains import validate_domain
from odoo_mcp.core.serializers import serialize_records
from odoo_mcp.security.audit import audit_action
from odoo_mcp.security.guards import guard_model_access, guard_write_fields


def odoo_search(
    client: OdooClient, user_id: int, model: str, domain: list[Any], limit: int
) -> list[int]:
    """Search for record IDs matching domain."""
    validate_domain(domain)
    return client.call_kw(
        model, "search", args=[domain], kwargs={"limit": limit}, sender_id=user_id
    )


def odoo_read(
    client: OdooClient,
    user_id: int,
    model: str,
    ids: list[int],
    fields: list[str] | None = None,
) -> list[dict[str, Any]]:
    """Read fields for a list of record IDs."""
    kwargs = {"fields": fields} if fields else {}
    records = client.call_kw(
        model, "read", args=[ids], kwargs=kwargs, sender_id=user_id
    )
    return serialize_records(records)


def odoo_search_read(
    client: OdooClient,
    user_id: int,
    model: str,
    domain: list[Any],
    fields: list[str] | None = None,
    limit: int = 80,
) -> list[dict[str, Any]]:
    """Search and read in a single call."""
    validate_domain(domain)
    kwargs = {"limit": limit}
    if fields:
        kwargs["fields"] = fields
    records = client.call_kw(
        model, "search_read", args=[domain], kwargs=kwargs, sender_id=user_id
    )
    return serialize_records(records)


def odoo_create(
    client: OdooClient, user_id: int, model: str, values: dict[str, Any]
) -> int:
    """Create a new record after checking allowlist."""
    guard_model_access(model)
    audit_action("CREATE", user_id, model, [], values)
    return client.call_kw(model, "create", args=[values], sender_id=user_id)


def odoo_write(
    client: OdooClient, user_id: int, model: str, ids: list[int], values: dict[str, Any]
) -> bool:
    """Update records, respecting denylists and allowlists."""
    guard_model_access(model)
    guard_write_fields(values)
    audit_action("WRITE", user_id, model, ids, values)
    return client.call_kw(model, "write", args=[ids, values], sender_id=user_id)
