SELECT table_name, view_definition
FROM v_catalog.views
WHERE table_schema = :schema
ORDER BY table_name;
