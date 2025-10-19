from mcp.server.fastmcp import FastMCP, Context
rows, prov = run_sql("repeat_issues_cluster.sql", {"schema": params.field_schema, "since": since, "cutoff": cutoff, "like_expr": like_expr, "cluster_boost": 20, "limit": params.limit})
return {"rows": rows, "provenance": prov.__dict__}


class BSOnCollection(BaseModel):
collection_id: str
as_of_ts: str | None = None
field_schema: str = Field(SCHEMA_DEFAULT)


@mcp.tool()
def business_services_on_collection(params: BSOnCollection) -> dict:
rows, prov = run_sql("business_services_on_collection.sql", {"schema": params.field_schema, "cluster": params.collection_id})
return {"applications": [r[0] for r in rows], "provenance": prov.__dict__}


class SimpleLimit(BaseModel):
field_schema: str = Field(SCHEMA_DEFAULT)
limit: int = 100


@mcp.tool()
def get_event_ci(params: SimpleLimit) -> dict:
rows, prov = run_sql("get_event_ci.sql", {"schema": params.field_schema, "limit": params.limit})
return {"rows": rows, "provenance": prov.__dict__}


class GKESearch(BaseModel):
application_keyword: str
field_schema: str = Field(SCHEMA_DEFAULT)
limit: int = 100


@mcp.tool()
def gke_identify_application_pod(params: GKESearch) -> dict:
q = f"%{params.application_keyword}%"
rows, prov = run_sql("gke_identify_application_pod.sql", {"schema": params.field_schema, "q": q, "limit": params.limit})
return {"pods": rows, "provenance": prov.__dict__}


class PodId(BaseModel):
pod_cmdb_id: str
field_schema: str = Field(SCHEMA_DEFAULT)


@mcp.tool()
def gke_identify_pod_cluster(params: PodId) -> dict:
rows, prov = run_sql("gke_pod_by_cmdb.sql", {"schema": params.field_schema, "pod_id": params.pod_cmdb_id})
return {"cluster": rows, "provenance": prov.__dict__}


@mcp.tool()
def gke_identify_pod_node(params: PodId) -> dict:
rows, prov = run_sql("gke_pod_node_by_cmdb.sql", {"schema": params.field_schema, "pod_id": params.pod_cmdb_id})
return {"node": rows, "provenance": prov.__dict__}


# Safe SELECT-only passthrough (read-only, with schema allowlist still enforced in SQL files)
class RawSelect(BaseModel):
query: str


@mcp.tool()
async def execute_query(ctx: Context, params: RawSelect) -> dict:
q = params.query.strip()
if not q.upper().startswith("SELECT "):
return {"error": "Only SELECT allowed in execute_query"}
# For safety, we do not run arbitrary q through run_sql (templates only). Keep a strict stance for POC.
return {"error": "Provide a templated tool/SQL file for this query"}
