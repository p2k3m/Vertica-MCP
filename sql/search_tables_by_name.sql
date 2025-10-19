SELECT table_schema || '.' || table_name AS fqtn, 0.7 AS score
FROM v_catalog.tables
WHERE is_system_table = false AND table_name ILIKE :q
LIMIT :limit;
