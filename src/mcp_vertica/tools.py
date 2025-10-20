"""Vertica-backed MCP tool definitions."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from mcp.server.fastmcp import Context, FastMCP
from pydantic import BaseModel, ConfigDict, Field, field_validator

from .config import settings
from .sqlman import Provenance, ensure_schema_allowed, ranked_multi, run_sql


def _schema_default() -> str:
    return settings.default_schema


def _iso_z(value: datetime) -> str:
    return value.isoformat().replace("+00:00", "Z")


def _prov_dict(prov: Provenance | list[Provenance]):
    if isinstance(prov, list):
        return [p.to_dict() for p in prov]
    return prov.to_dict()


class SchemaBound(BaseModel):
    model_config = ConfigDict(extra="forbid")

    field_schema: str = Field(default_factory=_schema_default)

    @field_validator("field_schema")
    @classmethod
    def _validate_schema(cls, value: str) -> str:
        return ensure_schema_allowed(value)


class Limited(SchemaBound):
    limit: int = Field(default=25, ge=1, le=settings.max_rows)


mcp = FastMCP("vertica")


class RepeatIssueParams(Limited):
    search: str | None = Field(default=None, max_length=128)
    days: int = Field(default=7, ge=1, le=90)


@mcp.tool()
def repeat_issues_cluster(params: RepeatIssueParams) -> dict[str, Any]:
    now = datetime.now(timezone.utc)
    since = _iso_z(now - timedelta(days=params.days))
    cutoff = _iso_z(now)
    like_expr = f"%{params.search}%" if params.search else "%"

    rows, provenance = run_sql(
        "repeat_issues_cluster.sql",
        {
            "schema": params.field_schema,
            "since": since,
            "cutoff": cutoff,
            "like_expr": like_expr,
            "cluster_boost": 20,
            "limit": params.limit,
        },
        limit=params.limit,
    )
    return {"rows": rows, "provenance": provenance.to_dict()}


class BSOnCollection(SchemaBound):
    collection_id: str
    as_of_ts: str | None = None


@mcp.tool()
def business_services_on_collection(params: BSOnCollection) -> dict[str, Any]:
    rows, provenance = run_sql(
        "business_services_on_collection.sql",
        {"schema": params.field_schema, "cluster": params.collection_id},
    )
    return {
        "applications": [row[0] for row in rows],
        "provenance": provenance.to_dict(),
    }


class SimpleLimit(Limited):
    pass


@mcp.tool()
def get_event_ci(params: SimpleLimit) -> dict[str, Any]:
    rows, provenance = run_sql(
        "get_event_ci.sql",
        {"schema": params.field_schema, "limit": params.limit},
        limit=params.limit,
    )
    return {"rows": rows, "provenance": provenance.to_dict()}


class GKESearch(Limited):
    application_keyword: str = Field(min_length=1, max_length=128)


@mcp.tool()
def gke_identify_application_pod(params: GKESearch) -> dict[str, Any]:
    like_expr = f"%{params.application_keyword}%"
    rows, provenance = run_sql(
        "gke_identify_application_pod.sql",
        {"schema": params.field_schema, "q": like_expr, "limit": params.limit},
        limit=params.limit,
    )
    return {"pods": rows, "provenance": provenance.to_dict()}


class PodId(SchemaBound):
    pod_cmdb_id: str


@mcp.tool()
def gke_identify_pod_cluster(params: PodId) -> dict[str, Any]:
    rows, provenance = run_sql(
        "gke_pod_by_cmdb.sql",
        {"schema": params.field_schema, "pod_id": params.pod_cmdb_id},
    )
    return {"cluster": rows, "provenance": provenance.to_dict()}


@mcp.tool()
def gke_identify_pod_node(params: PodId) -> dict[str, Any]:
    rows, provenance = run_sql(
        "gke_pod_node_by_cmdb.sql",
        {"schema": params.field_schema, "pod_id": params.pod_cmdb_id},
    )
    return {"node": rows, "provenance": provenance.to_dict()}


class SchemaSearch(Limited):
    term: str = Field(min_length=1, max_length=128)


@mcp.tool()
def search_schema_objects(params: SchemaSearch) -> dict[str, Any]:
    like_expr = f"%{params.term}%"
    ranked, provenances = ranked_multi(
        [
            (
                "search_tables_by_name.sql",
                {"schema": params.field_schema, "q": like_expr, "limit": params.limit},
            ),
            (
                "search_columns_by_name.sql",
                {"schema": params.field_schema, "q": like_expr, "limit": params.limit},
            ),
        ],
        k=params.limit,
    )
    results = [
        {"name": name, "score": score}
        for name, score in ranked
    ]
    return {"results": results, "provenance": _prov_dict(provenances)}


class RawSelect(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query: str


@mcp.tool()
async def execute_query(ctx: Context, params: RawSelect) -> dict[str, Any]:
    query = params.query.strip()
    if not query.upper().startswith("SELECT "):
        return {"error": "Only SELECT allowed in execute_query"}
    return {"error": "Provide a templated tool/SQL file for this query"}
