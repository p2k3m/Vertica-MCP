SELECT cluster_name, project_id, location
FROM :schema.cloud_gcp_gke_pod
WHERE cmdb_id = :pod_id
ORDER BY timestamp_utc_end_s DESC
LIMIT 1;
