SELECT e.event_id,
e.related_ci_display_label AS ci_name,
e.related_ci_cmdb_id AS ci_cmdb_id,
e.related_ci_cmdb_global_id,
e.related_ci_type
FROM :schema.opr_event e
LIMIT :limit;
