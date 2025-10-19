SELECT pod_name, pod_status, location, timestamp_utc_end_s
FROM :schema.cloud_gcp_gke_pod
WHERE cmdb_id = :ci_id
ORDER BY timestamp_utc_end_s DESC
LIMIT 1;
