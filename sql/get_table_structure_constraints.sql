SELECT constraint_name, constraint_type, column_name
FROM v_catalog.constraint_columns
WHERE table_schema = :schema AND table_name = :table;
