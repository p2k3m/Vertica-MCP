SELECT n.cmdb_id AS node_id, n.resource_name AS node_name, n.node_state, n.location
FROM :schema.cloud_gcp_gke_pod p
JOIN :schema.cloud_gcp_gke_node n
ON p.cluster_name = n.cluster_name AND p.resource_name = n.resource_name
WHERE p.cmdb_id = :pod_id
ORDER BY n.timestamp_utc_end_s DESC
LIMIT 1;
