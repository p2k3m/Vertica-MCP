SELECT 'gke_pod' AS ci_type, cmdb_id AS ci_id, pod_name AS name, location
FROM :schema.cloud_gcp_gke_pod
WHERE cluster_name = :cluster
LIMIT :limit;
