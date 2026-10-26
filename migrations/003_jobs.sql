-- Ingestion jobs (spip_tenant). Tenant-scoped like observation: RLS fails closed.

CREATE TABLE IF NOT EXISTS ingestion_job (
    job_id             text        PRIMARY KEY,
    tenant_id          text        NOT NULL,
    endpoint           text        NOT NULL,
    idempotency_key    text        NOT NULL,
    request_hash       text        NOT NULL,
    status             text        NOT NULL,
    entity_id          text        NOT NULL,
    upload_key         text        NOT NULL,
    scope              text        NOT NULL DEFAULT 'asset',
    reporting_year     integer,
    result             jsonb,
    error              text,
    attempts           integer     NOT NULL DEFAULT 0,
    lease_expires_at   timestamptz,
    created_at         timestamptz NOT NULL DEFAULT now(),
    updated_at         timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT ingestion_job_status_check CHECK (
        status IN ('PENDING', 'QUEUED', 'RUNNING', 'SUCCEEDED', 'FAILED')
    ),
    -- Retrying the same request must return the same job, never create a second.
    CONSTRAINT ingestion_job_idempotency_unique UNIQUE (tenant_id, endpoint, idempotency_key)
);

CREATE INDEX IF NOT EXISTS ingestion_job_tenant_status_idx
    ON ingestion_job (tenant_id, status);
CREATE INDEX IF NOT EXISTS ingestion_job_tenant_updated_idx
    ON ingestion_job (tenant_id, updated_at DESC);

ALTER TABLE ingestion_job ENABLE ROW LEVEL SECURITY;
ALTER TABLE ingestion_job FORCE ROW LEVEL SECURITY;

CREATE POLICY ingestion_job_tenant_isolation ON ingestion_job
    USING (tenant_id = current_setting('app.tenant_id', true));

-- Terminal states must never be moved back; enforce it in the database as well.
CREATE OR REPLACE FUNCTION ingestion_job_no_backwards() RETURNS trigger AS $$
BEGIN
    IF OLD.status IN ('SUCCEEDED', 'FAILED') AND NEW.status <> OLD.status THEN
        RAISE EXCEPTION 'job % is already terminal (%)', OLD.job_id, OLD.status;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS ingestion_job_no_backwards_trg ON ingestion_job;
CREATE TRIGGER ingestion_job_no_backwards_trg
    BEFORE UPDATE ON ingestion_job
    FOR EACH ROW EXECUTE FUNCTION ingestion_job_no_backwards();

--   GRANT SELECT, INSERT, UPDATE ON ingestion_job TO spip_app_tenant;
