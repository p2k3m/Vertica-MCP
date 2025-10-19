SELECT COUNT(*) AS alerts
FROM :schema.opr_event
WHERE related_ci_cmdb_id = :ci_id
AND lifecycle_state = 'open'
AND time_created BETWEEN :since AND :cutoff
AND (LOWER(category) LIKE '%security%' OR LOWER(title) LIKE '%security%' OR LOWER(description) LIKE '%security%');
