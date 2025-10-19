SELECT column_name, data_type, character_maximum_length,
numeric_precision, numeric_scale, is_nullable, column_default
FROM v_catalog.columns
WHERE table_schema = :schema AND table_name = :table
ORDER BY ordinal_position;
