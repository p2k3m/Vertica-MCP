SELECT projection_name, is_super_projection, anchor_table_name
FROM v_catalog.projections
WHERE projection_schema = :schema AND anchor_table_name = :table
ORDER BY projection_name;
