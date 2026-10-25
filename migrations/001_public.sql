-- Public baseline database (spip_public). Apply as a migration owner, not the app role.
-- The application role gets read access only; imports are done by a dedicated importer.

CREATE TABLE IF NOT EXISTS observation (
    tenant_id           text        NOT NULL DEFAULT 'PUBLIC',
    entity_id           text        NOT NULL,
    entity_name         text,
    postal_code         text,
    property_type       text,
    region              text,
    reporting_scope     text        NOT NULL,
    reporting_year      integer     NOT NULL,
    metric_code         text        NOT NULL,
    standardised_value  double precision,
    canonical_unit      text,
    comparability_status text,
    source_reference    text
);

CREATE INDEX IF NOT EXISTS observation_entity_idx
    ON observation (entity_id, reporting_year, metric_code);
CREATE INDEX IF NOT EXISTS observation_cohort_idx
    ON observation (reporting_scope, reporting_year, property_type, region);

-- RLS is not required for public rows (all are shared), but ordinary app
-- requests must never write. Grant only SELECT to the application role.
--   CREATE ROLE spip_app_public LOGIN;
--   GRANT CONNECT ON DATABASE spip_public TO spip_app_public;
--   GRANT SELECT ON observation TO spip_app_public;
--   GRANT SELECT ON ALL TABLES IN SCHEMA public TO spip_app_public;
