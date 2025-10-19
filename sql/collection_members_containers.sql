SELECT 'gke_container' AS ci_type, cmdb_id AS ci_id, resource_name AS name, location
FROM :schema.cloud_gcp_gke_container
WHERE cluster_name = :cluster
LIMIT :limit;
