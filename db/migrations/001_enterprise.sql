CREATE TABLE IF NOT EXISTS tenants (
    tenant_id text PRIMARY KEY,
    display_name text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS documents (
    document_id uuid PRIMARY KEY,
    tenant_id text NOT NULL REFERENCES tenants(tenant_id),
    display_name text NOT NULL,
    sha256 char(64) NOT NULL,
    status text NOT NULL CHECK (status IN ('processing', 'ready', 'failed', 'deleted')),
    page_count integer NOT NULL DEFAULT 0 CHECK (page_count >= 0),
    created_by_token text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    indexed_at timestamptz,
    retention_until timestamptz NOT NULL,
    deleted_at timestamptz
);

ALTER TABLE documents DROP CONSTRAINT IF EXISTS documents_tenant_id_sha256_key;
CREATE UNIQUE INDEX IF NOT EXISTS documents_active_digest_idx
    ON documents(tenant_id, sha256) WHERE deleted_at IS NULL;

CREATE TABLE IF NOT EXISTS assets (
    asset_id text NOT NULL,
    tenant_id text NOT NULL REFERENCES tenants(tenant_id),
    name text NOT NULL,
    site text NOT NULL,
    manufacturer text NOT NULL DEFAULT '',
    model text NOT NULL DEFAULT '',
    criticality text NOT NULL CHECK (criticality IN ('low', 'medium', 'high', 'safety_critical')),
    status text NOT NULL CHECK (status IN ('active', 'maintenance', 'out_of_service', 'retired')),
    updated_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, asset_id)
);

CREATE TABLE IF NOT EXISTS analysis_runs (
    answer_id uuid PRIMARY KEY,
    tenant_id text NOT NULL REFERENCES tenants(tenant_id),
    actor_token text NOT NULL,
    question_hash char(64) NOT NULL,
    answer_text text NOT NULL,
    use_case text NOT NULL,
    risk_class text NOT NULL,
    review_status text NOT NULL,
    provider text NOT NULL,
    deployment text NOT NULL,
    model_snapshot text NOT NULL,
    region text NOT NULL,
    prompt_key text NOT NULL,
    prompt_version text NOT NULL,
    citations jsonb NOT NULL DEFAULT '[]'::jsonb,
    generated_at timestamptz NOT NULL,
    retention_until timestamptz NOT NULL
);

CREATE TABLE IF NOT EXISTS analysis_reviews (
    review_id uuid PRIMARY KEY,
    tenant_id text NOT NULL REFERENCES tenants(tenant_id),
    answer_id uuid NOT NULL REFERENCES analysis_runs(answer_id),
    reviewer_token text NOT NULL,
    status text NOT NULL CHECK (status IN ('accepted', 'rejected', 'needs_expert')),
    reason_code text,
    reviewed_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS incidents (
    incident_id uuid PRIMARY KEY,
    tenant_id text NOT NULL REFERENCES tenants(tenant_id),
    asset_id text NOT NULL,
    title text NOT NULL,
    details text NOT NULL,
    severity text NOT NULL CHECK (severity IN ('ok', 'warning', 'critical', 'p1', 'p2', 'p3', 'p4')),
    status text NOT NULL CHECK (status IN ('new', 'acknowledged', 'in_progress', 'resolved', 'closed')),
    created_by_token text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    retention_until timestamptz NOT NULL
);

ALTER TABLE incidents ADD COLUMN IF NOT EXISTS retention_until timestamptz;
UPDATE incidents
SET retention_until = created_at + interval '730 days'
WHERE retention_until IS NULL;
ALTER TABLE incidents ALTER COLUMN retention_until SET NOT NULL;

CREATE TABLE IF NOT EXISTS notice_acceptances (
    acceptance_id uuid PRIMARY KEY,
    tenant_id text NOT NULL REFERENCES tenants(tenant_id),
    actor_token text NOT NULL,
    notice_type text NOT NULL CHECK (notice_type IN ('privacy', 'ai_literacy', 'terms')),
    version text NOT NULL,
    digest char(64) NOT NULL,
    accepted_at timestamptz NOT NULL DEFAULT now(),
    retention_until timestamptz NOT NULL,
    UNIQUE (tenant_id, actor_token, notice_type, version)
);

ALTER TABLE notice_acceptances ADD COLUMN IF NOT EXISTS retention_until timestamptz;
UPDATE notice_acceptances
SET retention_until = accepted_at + interval '3650 days'
WHERE retention_until IS NULL;
ALTER TABLE notice_acceptances ALTER COLUMN retention_until SET NOT NULL;

CREATE TABLE IF NOT EXISTS privacy_requests (
    request_id uuid PRIMARY KEY,
    tenant_id text NOT NULL REFERENCES tenants(tenant_id),
    subject_token text NOT NULL,
    request_type text NOT NULL CHECK (request_type IN ('access', 'export', 'rectification', 'restriction', 'erasure', 'objection')),
    status text NOT NULL CHECK (status IN ('submitted', 'identity_verified', 'in_review', 'completed', 'denied')),
    requested_at timestamptz NOT NULL DEFAULT now(),
    due_at timestamptz NOT NULL,
    completed_at timestamptz,
    evidence_reference text,
    retention_until timestamptz NOT NULL
);

CREATE TABLE IF NOT EXISTS audit_events (
    sequence_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    event_id uuid NOT NULL UNIQUE,
    tenant_id text NOT NULL REFERENCES tenants(tenant_id),
    action text NOT NULL,
    outcome text NOT NULL CHECK (outcome IN ('success', 'denied', 'failure')),
    actor_token text,
    resource_type text,
    resource_token text,
    metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
    occurred_at timestamptz NOT NULL,
    retention_until timestamptz NOT NULL,
    previous_hash char(64),
    event_hash char(64) NOT NULL
);

CREATE INDEX IF NOT EXISTS documents_tenant_status_idx ON documents(tenant_id, status);
CREATE INDEX IF NOT EXISTS assets_tenant_site_idx ON assets(tenant_id, site, name);
CREATE INDEX IF NOT EXISTS analysis_runs_tenant_generated_idx ON analysis_runs(tenant_id, generated_at DESC);
CREATE INDEX IF NOT EXISTS incidents_tenant_status_idx ON incidents(tenant_id, status, created_at DESC);
CREATE INDEX IF NOT EXISTS audit_events_tenant_sequence_idx ON audit_events(tenant_id, sequence_id);
CREATE INDEX IF NOT EXISTS privacy_requests_tenant_subject_idx ON privacy_requests(tenant_id, subject_token, requested_at DESC);
CREATE UNIQUE INDEX IF NOT EXISTS privacy_requests_active_unique_idx
    ON privacy_requests(tenant_id, subject_token, request_type)
    WHERE status NOT IN ('completed', 'denied');
CREATE INDEX IF NOT EXISTS retention_documents_idx ON documents(retention_until) WHERE deleted_at IS NULL;
CREATE INDEX IF NOT EXISTS retention_analysis_idx ON analysis_runs(retention_until);
CREATE INDEX IF NOT EXISTS retention_audit_idx ON audit_events(retention_until);
CREATE INDEX IF NOT EXISTS retention_privacy_request_idx ON privacy_requests(retention_until);
CREATE INDEX IF NOT EXISTS retention_notice_acceptance_idx ON notice_acceptances(retention_until);
CREATE INDEX IF NOT EXISTS retention_incident_idx ON incidents(retention_until);

ALTER TABLE tenants ENABLE ROW LEVEL SECURITY;
ALTER TABLE tenants FORCE ROW LEVEL SECURITY;
ALTER TABLE documents ENABLE ROW LEVEL SECURITY;
ALTER TABLE documents FORCE ROW LEVEL SECURITY;
ALTER TABLE assets ENABLE ROW LEVEL SECURITY;
ALTER TABLE assets FORCE ROW LEVEL SECURITY;
ALTER TABLE analysis_runs ENABLE ROW LEVEL SECURITY;
ALTER TABLE analysis_runs FORCE ROW LEVEL SECURITY;
ALTER TABLE analysis_reviews ENABLE ROW LEVEL SECURITY;
ALTER TABLE analysis_reviews FORCE ROW LEVEL SECURITY;
ALTER TABLE incidents ENABLE ROW LEVEL SECURITY;
ALTER TABLE incidents FORCE ROW LEVEL SECURITY;
ALTER TABLE notice_acceptances ENABLE ROW LEVEL SECURITY;
ALTER TABLE notice_acceptances FORCE ROW LEVEL SECURITY;
ALTER TABLE privacy_requests ENABLE ROW LEVEL SECURITY;
ALTER TABLE privacy_requests FORCE ROW LEVEL SECURITY;
ALTER TABLE audit_events ENABLE ROW LEVEL SECURITY;
ALTER TABLE audit_events FORCE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS tenant_tenants ON tenants;
CREATE POLICY tenant_tenants ON tenants USING (tenant_id = current_setting('app.tenant_id', true)) WITH CHECK (tenant_id = current_setting('app.tenant_id', true));
DROP POLICY IF EXISTS tenant_documents ON documents;
CREATE POLICY tenant_documents ON documents USING (tenant_id = current_setting('app.tenant_id', true)) WITH CHECK (tenant_id = current_setting('app.tenant_id', true));
DROP POLICY IF EXISTS tenant_assets ON assets;
CREATE POLICY tenant_assets ON assets USING (tenant_id = current_setting('app.tenant_id', true)) WITH CHECK (tenant_id = current_setting('app.tenant_id', true));
DROP POLICY IF EXISTS tenant_analysis_runs ON analysis_runs;
CREATE POLICY tenant_analysis_runs ON analysis_runs USING (tenant_id = current_setting('app.tenant_id', true)) WITH CHECK (tenant_id = current_setting('app.tenant_id', true));
DROP POLICY IF EXISTS tenant_analysis_reviews ON analysis_reviews;
CREATE POLICY tenant_analysis_reviews ON analysis_reviews USING (tenant_id = current_setting('app.tenant_id', true)) WITH CHECK (tenant_id = current_setting('app.tenant_id', true));
DROP POLICY IF EXISTS tenant_incidents ON incidents;
CREATE POLICY tenant_incidents ON incidents USING (tenant_id = current_setting('app.tenant_id', true)) WITH CHECK (tenant_id = current_setting('app.tenant_id', true));
DROP POLICY IF EXISTS tenant_notice_acceptances ON notice_acceptances;
CREATE POLICY tenant_notice_acceptances ON notice_acceptances USING (tenant_id = current_setting('app.tenant_id', true)) WITH CHECK (tenant_id = current_setting('app.tenant_id', true));
DROP POLICY IF EXISTS tenant_privacy_requests ON privacy_requests;
CREATE POLICY tenant_privacy_requests ON privacy_requests USING (tenant_id = current_setting('app.tenant_id', true)) WITH CHECK (tenant_id = current_setting('app.tenant_id', true));
DROP POLICY IF EXISTS tenant_audit_events ON audit_events;
CREATE POLICY tenant_audit_events ON audit_events USING (tenant_id = current_setting('app.tenant_id', true)) WITH CHECK (tenant_id = current_setting('app.tenant_id', true));

REVOKE UPDATE, DELETE ON audit_events FROM PUBLIC;

CREATE OR REPLACE FUNCTION purge_expired_tenant_data(p_tenant_id text)
RETURNS jsonb
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, public
AS $$
DECLARE
    reviews_deleted integer := 0;
    analyses_deleted integer := 0;
    incidents_deleted integer := 0;
    notices_deleted integer := 0;
    requests_deleted integer := 0;
    documents_deleted integer := 0;
    audits_deleted integer := 0;
BEGIN
    DELETE FROM public.analysis_reviews AS review
    USING public.analysis_runs AS analysis
    WHERE review.answer_id = analysis.answer_id
      AND review.tenant_id = p_tenant_id
      AND analysis.tenant_id = p_tenant_id
      AND analysis.retention_until <= now();
    GET DIAGNOSTICS reviews_deleted = ROW_COUNT;

    DELETE FROM public.analysis_runs
    WHERE tenant_id = p_tenant_id AND retention_until <= now();
    GET DIAGNOSTICS analyses_deleted = ROW_COUNT;

    DELETE FROM public.incidents
    WHERE tenant_id = p_tenant_id AND retention_until <= now();
    GET DIAGNOSTICS incidents_deleted = ROW_COUNT;

    DELETE FROM public.notice_acceptances
    WHERE tenant_id = p_tenant_id AND retention_until <= now();
    GET DIAGNOSTICS notices_deleted = ROW_COUNT;

    DELETE FROM public.privacy_requests
    WHERE tenant_id = p_tenant_id AND retention_until <= now();
    GET DIAGNOSTICS requests_deleted = ROW_COUNT;

    DELETE FROM public.documents
    WHERE tenant_id = p_tenant_id AND deleted_at IS NOT NULL AND retention_until <= now();
    GET DIAGNOSTICS documents_deleted = ROW_COUNT;

    DELETE FROM public.audit_events
    WHERE tenant_id = p_tenant_id AND retention_until <= now();
    GET DIAGNOSTICS audits_deleted = ROW_COUNT;

    RETURN jsonb_build_object(
        'analysis_reviews', reviews_deleted,
        'analysis_runs', analyses_deleted,
        'incidents', incidents_deleted,
        'notice_acceptances', notices_deleted,
        'privacy_requests', requests_deleted,
        'documents', documents_deleted,
        'audit_events', audits_deleted
    );
END;
$$;

REVOKE ALL ON FUNCTION purge_expired_tenant_data(text) FROM PUBLIC;

CREATE OR REPLACE FUNCTION list_retention_tenant_ids()
RETURNS TABLE(tenant_id text)
LANGUAGE sql
SECURITY DEFINER
SET search_path = pg_catalog, public
AS $$
    SELECT tenant.tenant_id
    FROM public.tenants AS tenant
    ORDER BY tenant.tenant_id
$$;

REVOKE ALL ON FUNCTION list_retention_tenant_ids() FROM PUBLIC;
