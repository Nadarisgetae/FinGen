-- FinGen v2 — Row Level Security Policies
-- Run AFTER 001_init.sql

-- =============================================================================
-- Enable RLS on all tables
-- =============================================================================

ALTER TABLE companies ENABLE ROW LEVEL SECURITY;
ALTER TABLE documents ENABLE ROW LEVEL SECURITY;
ALTER TABLE facts ENABLE ROW LEVEL SECURITY;
ALTER TABLE assumptions ENABLE ROW LEVEL SECURITY;
ALTER TABLE reports ENABLE ROW LEVEL SECURITY;
ALTER TABLE jobs ENABLE ROW LEVEL SECURITY;
ALTER TABLE llm_cache ENABLE ROW LEVEL SECURITY;
ALTER TABLE llm_calls ENABLE ROW LEVEL SECURITY;
ALTER TABLE portfolios ENABLE ROW LEVEL SECURITY;
ALTER TABLE holdings ENABLE ROW LEVEL SECURITY;
ALTER TABLE transactions ENABLE ROW LEVEL SECURITY;
ALTER TABLE price_history ENABLE ROW LEVEL SECURITY;
ALTER TABLE review_queue ENABLE ROW LEVEL SECURITY;
ALTER TABLE narrative_snippets ENABLE ROW LEVEL SECURITY;

-- =============================================================================
-- Policies: companies
-- =============================================================================

CREATE POLICY "companies_select_own" ON companies
    FOR SELECT USING (user_id = auth.uid());

CREATE POLICY "companies_insert_own" ON companies
    FOR INSERT WITH CHECK (user_id = auth.uid());

CREATE POLICY "companies_update_own" ON companies
    FOR UPDATE USING (user_id = auth.uid()) WITH CHECK (user_id = auth.uid());

CREATE POLICY "companies_delete_own" ON companies
    FOR DELETE USING (user_id = auth.uid());

-- =============================================================================
-- Policies: documents
-- =============================================================================

CREATE POLICY "documents_select_own" ON documents
    FOR SELECT USING (user_id = auth.uid());

CREATE POLICY "documents_insert_own" ON documents
    FOR INSERT WITH CHECK (user_id = auth.uid());

CREATE POLICY "documents_update_own" ON documents
    FOR UPDATE USING (user_id = auth.uid()) WITH CHECK (user_id = auth.uid());

CREATE POLICY "documents_delete_own" ON documents
    FOR DELETE USING (user_id = auth.uid());

-- =============================================================================
-- Policies: facts
-- =============================================================================

CREATE POLICY "facts_select_own" ON facts
    FOR SELECT USING (user_id = auth.uid());

CREATE POLICY "facts_insert_own" ON facts
    FOR INSERT WITH CHECK (user_id = auth.uid());

CREATE POLICY "facts_update_own" ON facts
    FOR UPDATE USING (user_id = auth.uid()) WITH CHECK (user_id = auth.uid());

CREATE POLICY "facts_delete_own" ON facts
    FOR DELETE USING (user_id = auth.uid());

-- =============================================================================
-- Policies: assumptions
-- =============================================================================

CREATE POLICY "assumptions_select_own" ON assumptions
    FOR SELECT USING (user_id = auth.uid());

CREATE POLICY "assumptions_insert_own" ON assumptions
    FOR INSERT WITH CHECK (user_id = auth.uid());

CREATE POLICY "assumptions_update_own" ON assumptions
    FOR UPDATE USING (user_id = auth.uid()) WITH CHECK (user_id = auth.uid());

CREATE POLICY "assumptions_delete_own" ON assumptions
    FOR DELETE USING (user_id = auth.uid());

-- =============================================================================
-- Policies: reports
-- =============================================================================

CREATE POLICY "reports_select_own" ON reports
    FOR SELECT USING (user_id = auth.uid());

CREATE POLICY "reports_insert_own" ON reports
    FOR INSERT WITH CHECK (user_id = auth.uid());

CREATE POLICY "reports_update_own" ON reports
    FOR UPDATE USING (user_id = auth.uid()) WITH CHECK (user_id = auth.uid());

CREATE POLICY "reports_delete_own" ON reports
    FOR DELETE USING (user_id = auth.uid());

-- =============================================================================
-- Policies: jobs
-- =============================================================================

CREATE POLICY "jobs_select_own" ON jobs
    FOR SELECT USING (user_id = auth.uid());

CREATE POLICY "jobs_insert_own" ON jobs
    FOR INSERT WITH CHECK (user_id = auth.uid());

CREATE POLICY "jobs_update_own" ON jobs
    FOR UPDATE USING (user_id = auth.uid()) WITH CHECK (user_id = auth.uid());

CREATE POLICY "jobs_delete_own" ON jobs
    FOR DELETE USING (user_id = auth.uid());

-- =============================================================================
-- Policies: llm_cache (global read, service key write)
-- =============================================================================

-- Cache is global (shared across users) - read allowed for authenticated users
CREATE POLICY "llm_cache_select_authenticated" ON llm_cache
    FOR SELECT USING (auth.role() = 'authenticated');

-- Only service role can insert/update/delete (via server-side code)
CREATE POLICY "llm_cache_service_write" ON llm_cache
    FOR ALL USING (auth.role() = 'service_role') WITH CHECK (auth.role() = 'service_role');

-- =============================================================================
-- Policies: llm_calls (user sees own, service sees all)
-- =============================================================================

CREATE POLICY "llm_calls_select_own" ON llm_calls
    FOR SELECT USING (user_id = auth.uid());

CREATE POLICY "llm_calls_service_all" ON llm_calls
    FOR ALL USING (auth.role() = 'service_role') WITH CHECK (auth.role() = 'service_role');

-- =============================================================================
-- Policies: portfolios
-- =============================================================================

CREATE POLICY "portfolios_select_own" ON portfolios
    FOR SELECT USING (user_id = auth.uid());

CREATE POLICY "portfolios_insert_own" ON portfolios
    FOR INSERT WITH CHECK (user_id = auth.uid());

CREATE POLICY "portfolios_update_own" ON portfolios
    FOR UPDATE USING (user_id = auth.uid()) WITH CHECK (user_id = auth.uid());

CREATE POLICY "portfolios_delete_own" ON portfolios
    FOR DELETE USING (user_id = auth.uid());

-- =============================================================================
-- Policies: holdings
-- =============================================================================

CREATE POLICY "holdings_select_own" ON holdings
    FOR SELECT USING (user_id = auth.uid());

CREATE POLICY "holdings_insert_own" ON holdings
    FOR INSERT WITH CHECK (user_id = auth.uid());

CREATE POLICY "holdings_update_own" ON holdings
    FOR UPDATE USING (user_id = auth.uid()) WITH CHECK (user_id = auth.uid());

CREATE POLICY "holdings_delete_own" ON holdings
    FOR DELETE USING (user_id = auth.uid());

-- =============================================================================
-- Policies: transactions
-- =============================================================================

CREATE POLICY "transactions_select_own" ON transactions
    FOR SELECT USING (user_id = auth.uid());

CREATE POLICY "transactions_insert_own" ON transactions
    FOR INSERT WITH CHECK (user_id = auth.uid());

CREATE POLICY "transactions_update_own" ON transactions
    FOR UPDATE USING (user_id = auth.uid()) WITH CHECK (user_id = auth.uid());

CREATE POLICY "transactions_delete_own" ON transactions
    FOR DELETE USING (user_id = auth.uid());

-- =============================================================================
-- Policies: price_history (global read for authenticated users)
-- =============================================================================

CREATE POLICY "price_history_select_authenticated" ON price_history
    FOR SELECT USING (auth.role() = 'authenticated');

CREATE POLICY "price_history_service_write" ON price_history
    FOR ALL USING (auth.role() = 'service_role') WITH CHECK (auth.role() = 'service_role');

-- =============================================================================
-- Policies: review_queue
-- =============================================================================

CREATE POLICY "review_queue_select_own" ON review_queue
    FOR SELECT USING (user_id = auth.uid());

CREATE POLICY "review_queue_insert_own" ON review_queue
    FOR INSERT WITH CHECK (user_id = auth.uid());

CREATE POLICY "review_queue_update_own" ON review_queue
    FOR UPDATE USING (user_id = auth.uid()) WITH CHECK (user_id = auth.uid());

-- =============================================================================
-- Policies: narrative_snippets
-- =============================================================================

CREATE POLICY "narrative_snippets_select_own" ON narrative_snippets
    FOR SELECT USING (user_id = auth.uid());

CREATE POLICY "narrative_snippets_insert_own" ON narrative_snippets
    FOR INSERT WITH CHECK (user_id = auth.uid());

-- =============================================================================
-- Storage bucket policies (run in Supabase Dashboard SQL editor)
-- =============================================================================

-- NOTE: Storage policies must be created via Supabase Dashboard or storage API
-- These are reference policies for the buckets:

-- Bucket: uploads (private, user-scoped)
-- Policy: "uploads_user_access"
--   CREATE POLICY "uploads_user_access" ON storage.objects
--   FOR ALL USING (
--     bucket_id = 'uploads' AND
--     (auth.uid()::text = (storage.foldername(name))[1])
--   );

-- Bucket: reports (private, user-scoped)
-- Policy: "reports_user_access"
--   CREATE POLICY "reports_user_access" ON storage.objects
--   FOR ALL USING (
--     bucket_id = 'reports' AND
--     (auth.uid()::text = (storage.foldername(name))[1])
--   );

-- =============================================================================
-- Helper function for service role bypass
-- =============================================================================

-- Create a function that allows service role to bypass RLS for specific operations
-- This is used by the job worker and cache writer

CREATE OR REPLACE FUNCTION service_role_bypass()
RETURNS BOOLEAN AS $$
BEGIN
    RETURN auth.role() = 'service_role';
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;