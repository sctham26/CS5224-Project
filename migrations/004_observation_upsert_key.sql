-- Upsert key for observation (spip_public). Required by the baseline importer:
-- re-running an import corrects rows in place instead of duplicating them, which
-- would silently inflate peer cohorts.

CREATE UNIQUE INDEX IF NOT EXISTS observation_upsert_key
    ON observation (tenant_id, entity_id, reporting_year, reporting_scope, metric_code);
