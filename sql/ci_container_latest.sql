SELECT resource_name AS container_name, pod_name, cpu_limit_util_pct_mean, mem_limit_util_pct_mean, restart_count_rate, timestamp_utc_end_s
FROM :schema.cloud_gcp_gke_container
WHERE cmdb_id = :ci_id
ORDER BY timestamp_utc_end_s DESC
LIMIT 1;
