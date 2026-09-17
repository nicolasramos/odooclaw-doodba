"""Tests for odoo_count — deterministic counting (NRA-556 regression).

`odoo_count` returns Odoo's own search_count. It exists because counting the
IDs a search returns is silently wrong: the search tools are paginated
(odoo_search_read defaults to 80), so a count taken from a result list is
capped at the page size while looking perfectly healthy.

That is not hypothetical — it is the bug these tests guard against. With 59
partners in the demo DB, the bot answered "50 clients" because it counted a
50-row page. The tool was dropped by a later core subtree sync, so the model
silently fell back to counting a truncated list.

The distinction these tests pin down: odoo_count must call `search_count`
(one integer, computed by the database), never `search` (a list that can be
truncated).
"""

from unittest.mock import MagicMock

import pytest

from odoo_mcp.core.client import OdooClient
from odoo_mcp.tools import records


@pytest.fixture
def mock_client():
    return MagicMock(spec=OdooClient)


def test_count_uses_search_count_not_search(mock_client):
    """The whole point: count via search_count, never by counting a list."""
    mock_client.call_kw.return_value = 59

    result = records.odoo_count(mock_client, user_id=2, model="res.partner", domain=[])

    assert result == 59
    method = mock_client.call_kw.call_args.args[1]
    assert method == "search_count", (
        "odoo_count must ask Odoo for the count directly; using 'search' would "
        "return a paginated list and the count would be capped at page size"
    )
    assert "limit" not in mock_client.call_kw.call_args.kwargs, (
        "a count must never be limited — that is exactly the truncation bug"
    )


def test_count_passes_domain_through(mock_client):
    """A filtered count must reach Odoo unchanged."""
    mock_client.call_kw.return_value = 17
    domain = [["state", "=", "sale"], ["date_order", ">=", "2026-09-01"]]

    result = records.odoo_count(mock_client, user_id=2, model="sale.order", domain=domain)

    assert result == 17
    assert mock_client.call_kw.call_args.kwargs["args"] == [domain]


def test_count_empty_domain_counts_everything(mock_client):
    """domain=[] means 'count all' — the 'how many customers' case."""
    mock_client.call_kw.return_value = 59

    result = records.odoo_count(mock_client, user_id=2, model="res.partner", domain=[])

    assert result == 59
    assert mock_client.call_kw.call_args.kwargs["args"] == [[]]


def test_count_malformed_domain_falls_back_to_all(mock_client):
    """A bad domain must not raise; count everything, like odoo_search does."""
    mock_client.call_kw.return_value = 59

    # not a list of conditions — validate_domain should reject this
    result = records.odoo_count(mock_client, user_id=2, model="res.partner", domain="not-a-domain")

    assert result == 59
    assert mock_client.call_kw.call_args.kwargs["args"] == [[]]
