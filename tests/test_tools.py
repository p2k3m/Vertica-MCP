from __future__ import annotations

import asyncio
import importlib
from datetime import datetime, timezone

import pytest

from mcp_vertica import tools
from mcp_vertica.sqlman import Provenance


def _prov(name: str) -> Provenance:
    return Provenance(name, {}, datetime.now(timezone.utc).isoformat(), 0, 0.0)


def test_mcp_http_transport_binds_public_interface() -> None:
    with pytest.MonkeyPatch.context() as mp:
        for key in ("LISTEN_HOST", "MCP_LISTEN_HOST", "BIND_HOST", "MCP_BIND_HOST", "HOST", "ALLOW_LOOPBACK_LISTEN"):
            mp.delenv(key, raising=False)
        importlib.reload(tools)
        assert tools.mcp.settings.host == "0.0.0.0"
        assert tools.mcp.settings.port == 8000

    importlib.reload(tools)


def test_mcp_http_transport_honours_listen_env() -> None:
    with pytest.MonkeyPatch.context() as mp:
        mp.setenv("LISTEN_HOST", "10.10.0.5")
        mp.setenv("LISTEN_PORT", "9100")
        importlib.reload(tools)
        assert tools.mcp.settings.host == "10.10.0.5"
        assert tools.mcp.settings.port == 9100

    importlib.reload(tools)


def test_repeat_issues_cluster_returns_provenance(monkeypatch: pytest.MonkeyPatch):
    captured = {}

    def fake_run_sql(name, params, limit=None):
        captured["call"] = (name, params, limit)
        return [("row",)], _prov(name)

    monkeypatch.setattr(tools, "run_sql", fake_run_sql)

    result = tools.repeat_issues_cluster(
        tools.RepeatIssueParams(field_schema="public", search="app", days=1, limit=5)
    )

    call_name, call_params, call_limit = captured["call"]
    assert call_name == "repeat_issues_cluster.sql"
    assert call_params["schema"] == "public"
    assert call_params["limit"] == 5
    assert call_limit == 5
    assert result["provenance"]["sql_or_view"] == "repeat_issues_cluster.sql"


def test_search_schema_objects_uses_ranked_multi(monkeypatch: pytest.MonkeyPatch):
    provs = [_prov("tables"), _prov("columns")]

    def fake_ranked_multi(queries, k=50):
        return [("foo", 0.9)], provs

    monkeypatch.setattr(tools, "ranked_multi", fake_ranked_multi)

    result = tools.search_schema_objects(
        tools.SchemaSearch(field_schema="public", term="foo", limit=5)
    )

    assert result["results"] == [{"name": "foo", "score": 0.9}]
    assert len(result["provenance"]) == 2
    assert {p["sql_or_view"] for p in result["provenance"]} == {"tables", "columns"}


def test_execute_query_rejects_non_select():
    result = asyncio.run(
        tools.execute_query(None, tools.RawSelect(query="UPDATE foo SET bar = 1"))
    )

    assert "Only SELECT" in result["error"]


def test_execute_query_requires_templated_tool():
    result = asyncio.run(
        tools.execute_query(None, tools.RawSelect(query="SELECT * FROM something"))
    )

    assert "templated" in result["error"]
