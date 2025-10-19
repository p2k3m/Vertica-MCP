SELECT DISTINCT pod_name, cmdb_id AS pod_id, cluster_name
FROM :schema.cloud_gcp_gke_pod
WHERE pod_name ILIKE :q OR resource_name ILIKE :q
LIMIT :limit;
