WITH hits AS (
SELECT 'gke_pod' AS source, cmdb_id, cluster_name, location, project_id, pod_name AS name, timestamp_utc_end_s
FROM :schema.cloud_gcp_gke_pod
WHERE (:ci_id IS NOT NULL AND cmdb_id = :ci_id)
OR (:ci_name IS NOT NULL AND (pod_name ILIKE :like OR resource_name ILIKE :like))
UNION ALL
SELECT 'gke_node', cmdb_id, cluster_name, location, project_id, resource_name, timestamp_utc_end_s
FROM :schema.cloud_gcp_gke_node
WHERE (:ci_id IS NOT NULL AND cmdb_id = :ci_id)
OR (:ci_name IS NOT NULL AND (resource_name ILIKE :like))
UNION ALL
SELECT 'gke_container', cmdb_id, cluster_name, location, project_id, resource_name, timestamp_utc_end_s
FROM :schema.cloud_gcp_gke_container
WHERE (:ci_id IS NOT NULL AND cmdb_id = :ci_id)
OR (:ci_name IS NOT NULL AND (resource_name ILIKE :like OR pod_name ILIKE :like))
), ranked AS (
SELECT *, ROW_NUMBER() OVER (ORDER BY timestamp_utc_end_s DESC) rn
FROM hits
)
SELECT source, cluster_name, location, project_id, name
FROM ranked WHERE rn = 1;
