SELECT table_schema || '.' || table_name AS fqtn, column_name, 0.3 AS score
FROM v_catalog.columns
WHERE column_name ILIKE :q
LIMIT :limit;
