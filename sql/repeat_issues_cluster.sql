WITH cand AS (
SELECT event_id, title, description, related_ci_cmdb_id, duplicate_count, time_created, application,
related_ci_display_label AS ci_name
FROM :schema.opr_event
WHERE time_created BETWEEN :since AND :cutoff
AND :like_expr
), scored AS (
SELECT c.*,
EXTRACT(EPOCH FROM (:cutoff::timestamp - c.time_created::timestamp))/3600.0 AS age_hours
FROM cand c
)
SELECT event_id, ci_name, related_ci_cmdb_id, application, duplicate_count, time_created,
(GREATEST(0, 72 - age_hours)) + (duplicate_count * 5) + (:cluster_boost) AS rank_score
FROM scored
ORDER BY rank_score DESC
LIMIT :limit;
