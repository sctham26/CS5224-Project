-- Tenant database (spip_tenant): private ESG rows plus backend-owned bookkeeping.
-- Apply as a migration owner. The application role must NOT own these tables and
-- must not have BYPASSRLS, otherwise the policies below are unenforced.

CREATE TABLE IF NOT EXISTS observation (
    tenant_id           text        NOT NULL,
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

CREATE INDEX IF NOT EXISTS observation_tenant_entity_idx
    ON observation (tenant_id, entity_id, reporting_year, metric_code);

-- Membership: the only source of truth for "which tenant may this user read".
-- Deliberately not writable from the browser and not derived from Cognito
-- attributes (see docs/AUTH_CONTRACT.md).
CREATE TABLE IF NOT EXISTS tenant_membership (
    user_sub    text        NOT NULL,
    tenant_id   text        NOT NULL,
    active      boolean     NOT NULL DEFAULT true,
    PRIMARY KEY (user_sub)
);

ALTER TABLE observation ENABLE ROW LEVEL SECURITY;
ALTER TABLE observation FORCE ROW LEVEL SECURITY;

-- Fail closed: when app.tenant_id is unset, current_setting(..., true) is NULL
-- and no rows match. The API sets it with SET LOCAL inside the transaction.
CREATE POLICY observation_tenant_isolation ON observation
    USING (tenant_id = current_setting('app.tenant_id', true));

ALTER TABLE tenant_membership ENABLE ROW LEVEL SECURITY;
ALTER TABLE tenant_membership FORCE ROW LEVEL SECURITY;

CREATE POLICY tenant_membership_self ON tenant_membership
    USING (user_sub = current_setting('app.user_sub', true));

--   CREATE ROLE spip_app_tenant LOGIN;
--   GRANT CONNECT ON DATABASE spip_tenant TO spip_app_tenant;
--   GRANT SELECT ON observation, tenant_membership TO spip_app_tenant;
