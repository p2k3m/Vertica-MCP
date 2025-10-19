SELECT DISTINCT application
FROM :schema.opr_event
WHERE application IS NOT NULL AND TRIM(application) <> ''
LIMIT :limit;
