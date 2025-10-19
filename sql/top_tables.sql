SELECT table_schema || '.' || table_name AS fqtn
FROM v_catalog.tables
WHERE is_system_table = false
AND (:like IS NULL OR table_name ILIKE :like)
ORDER BY table_schema, table_name
LIMIT :limit;
