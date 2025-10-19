WITH cis AS (
SELECT cmdb_id FROM :schema.cloud_gcp_gke_pod WHERE cluster_name = :cluster
UNION
SELECT cmdb_id FROM :schema.cloud_gcp_gke_node WHERE cluster_name = :cluster
UNION
SELECT cmdb_id FROM :schema.cloud_gcp_gke_container WHERE cluster_name = :cluster
)
SELECT DISTINCT application
FROM :schema.opr_event e
WHERE e.related_ci_cmdb_id IN (SELECT cmdb_id FROM cis)
AND e.application IS NOT NULL AND TRIM(e.application) <> '';
