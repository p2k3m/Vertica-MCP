SELECT ci_id, ci_name, ci_type, location, rel_path
FROM v_bs_to_ci_edges
WHERE bs_id = :bs_id;
