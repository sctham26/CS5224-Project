-- Enable UUID extension if not already present
CREATE EXTENSION IF NOT EXISTS "pgcrypto";

-- Drop existing types/tables if re-running init
DROP POLICY IF EXISTS tenant_isolation_policy ON Standardised_ESG_Records;
DROP TABLE IF EXISTS Standardised_ESG_Records;
DROP TYPE IF EXISTS comparability_flag;
DROP TYPE IF EXISTS entity_scope;
DROP TYPE IF EXISTS visibility_scope;

-- Create Enums matching SPIP data contract
CREATE TYPE visibility_scope AS ENUM ('PUBLIC_BASELINE', 'PRIVATE_TENANT');
CREATE TYPE entity_scope AS ENUM ('ASSET', 'PORTFOLIO');
CREATE TYPE comparability_flag AS ENUM ('COMPARABLE', 'UNIT_CONVERTED', 'BOUNDARY_MISMATCH', 'INCOMPLETE_DATA', 'ANOMALY_FLAGGED');

-- Canonical Table for Ingested & Harmonised ESG Records
CREATE TABLE Standardised_ESG_Records (
    record_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id VARCHAR(64) NOT NULL,               -- 'PUBLIC' for BCA/SGX; UUID or slug for private tenants
    visibility visibility_scope NOT NULL,
    entity_id VARCHAR(128) NOT NULL,              -- Postal code, Building ID, or SGX Ticker
    entity_name VARCHAR(255) NOT NULL,
    property_type VARCHAR(64) NOT NULL,           -- e.g., 'OFFICE', 'RETAIL', 'HOTEL', 'MIXED_DEVELOPMENT'
    region VARCHAR(64) NOT NULL DEFAULT 'SG',     -- e.g., 'SG_CBD', 'SG_CENTRAL_ORCHARD', 'SG_WEST'
    reporting_scope entity_scope NOT NULL,        -- 'ASSET' vs 'PORTFOLIO'
    reporting_year INT NOT NULL,                  -- e.g., 2023, 2024, 2025
    gross_floor_area_sqm NUMERIC(12, 2),          -- Always harmonised to m²
    metric_code VARCHAR(64) NOT NULL,             -- Foreign key to Metric Dictionary (e.g., 'ENERGY_INTENSITY_EUI')
    raw_value NUMERIC(18, 6),                     -- Original value uploaded by tenant or scraped
    raw_unit VARCHAR(32),                         -- Original unit uploaded (e.g., 'sqft', 'GJ/m2/yr')
    standardised_value NUMERIC(18, 6),            -- Harmonised canonical value; NULL if missing
    canonical_unit VARCHAR(32) NOT NULL,          -- e.g., 'kWh/m2/yr', 'kgCO2e/m2/yr'
    comparability_status comparability_flag NOT NULL,
    source_reference VARCHAR(255) NOT NULL,       -- e.g., 'BCA_BEBR_2025', 'SGX_CICT_FY24', 'TENANT_UPLOAD'
    ingested_at TIMESTAMPTZ DEFAULT NOW(),
    
    -- Prevent duplicate metric entries for the same entity, year, and tenant
    UNIQUE (tenant_id, entity_id, reporting_year, metric_code, reporting_scope)
);

-- Create Index for fast peer cohort filtering (TC-3)
CREATE INDEX idx_peer_filtering ON Standardised_ESG_Records (property_type, region, reporting_year, metric_code, comparability_status);

-- Enable Row-Level Security for TC-5 Multi-Tenant Privacy
ALTER TABLE Standardised_ESG_Records ENABLE ROW LEVEL SECURITY;

-- RLS Policy: Public records are visible to all; private records are restricted to the authenticated tenant session
CREATE POLICY tenant_isolation_policy ON Standardised_ESG_Records
    USING (
        visibility = 'PUBLIC_BASELINE' 
        OR tenant_id = current_setting('app.current_tenant_id', true)
    );