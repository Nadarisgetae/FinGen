-- FinGen v2 — Indexes & Performance
-- Run AFTER 001_init.sql, 002_rls.sql

-- =============================================================================
-- Companies indexes
-- =============================================================================

CREATE INDEX IF NOT EXISTS idx_companies_user_id ON companies(user_id);
CREATE INDEX IF NOT EXISTS idx_companies_ticker ON companies(ticker);
CREATE INDEX IF NOT EXISTS idx_companies_user_ticker ON companies(user_id, ticker);

-- =============================================================================
-- Documents indexes
-- =============================================================================

CREATE INDEX IF NOT EXISTS idx_documents_company_id ON documents(company_id);
CREATE INDEX IF NOT EXISTS idx_documents_user_id ON documents(user_id);
CREATE INDEX IF NOT EXISTS idx_documents_status ON documents(status);
CREATE INDEX IF NOT EXISTS idx_documents_type ON documents(type);
CREATE INDEX IF NOT EXISTS idx_documents_fiscal_year ON documents(fiscal_year);
CREATE INDEX IF NOT EXISTS idx_documents_sha256 ON documents(sha256);
CREATE INDEX IF NOT EXISTS idx_documents_company_type_year ON documents(company_id, type, fiscal_year);

-- =============================================================================
-- Facts indexes (critical for query performance)
-- =============================================================================

CREATE INDEX IF NOT EXISTS idx_facts_company_id ON facts(company_id);
CREATE INDEX IF NOT EXISTS idx_facts_user_id ON facts(user_id);
CREATE INDEX IF NOT EXISTS idx_facts_document_id ON facts(document_id);
CREATE INDEX IF NOT EXISTS idx_facts_statement ON facts(statement);
CREATE INDEX IF NOT EXISTS idx_facts_line_item ON facts(line_item);
CREATE INDEX IF NOT EXISTS idx_facts_period ON facts(period);
CREATE INDEX IF NOT EXISTS idx_facts_company_statement_period ON facts(company_id, statement, period);
CREATE INDEX IF NOT EXISTS idx_facts_company_line_item_period ON facts(company_id, line_item, period);
CREATE INDEX IF NOT EXISTS idx_facts_company_statement_line_item_period ON facts(company_id, statement, line_item, period);
CREATE INDEX IF NOT EXISTS idx_facts_edited_by_user ON facts(edited_by_user);

-- Composite for common query patterns
CREATE INDEX IF NOT EXISTS idx_facts_company_is_period ON facts(company_id, period) WHERE statement = 'IS';
CREATE INDEX IF NOT EXISTS idx_facts_company_bs_period ON facts(company_id, period) WHERE statement = 'BS';
CREATE INDEX IF NOT EXISTS idx_facts_company_cf_period ON facts(company_id, period) WHERE statement = 'CF';

-- =============================================================================
-- Assumptions indexes
-- =============================================================================

CREATE INDEX IF NOT EXISTS idx_assumptions_company_id ON assumptions(company_id);
CREATE INDEX IF NOT EXISTS idx_assumptions_user_id ON assumptions(user_id);
CREATE INDEX IF NOT EXISTS idx_assumptions_scenario ON assumptions(scenario);
CREATE INDEX IF NOT EXISTS idx_assumptions_driver ON assumptions(driver);
CREATE INDEX IF NOT EXISTS idx_assumptions_company_scenario_driver ON assumptions(company_id, scenario, driver);

-- =============================================================================
-- Reports indexes
-- =============================================================================

CREATE INDEX IF NOT EXISTS idx_reports_company_id ON reports(company_id);
CREATE INDEX IF NOT EXISTS idx_reports_user_id ON reports(user_id);
CREATE INDEX IF NOT EXISTS idx_reports_type ON reports(type);
CREATE INDEX IF NOT EXISTS idx_reports_status ON reports(status);
CREATE INDEX IF NOT EXISTS idx_reports_company_type ON reports(company_id, type);
CREATE INDEX IF NOT EXISTS idx_reports_created_at ON reports(created_at DESC);

-- =============================================================================
-- Jobs indexes
-- =============================================================================

CREATE INDEX IF NOT EXISTS idx_jobs_user_id ON jobs(user_id);
CREATE INDEX IF NOT EXISTS idx_jobs_company_id ON jobs(company_id);
CREATE INDEX IF NOT EXISTS idx_jobs_kind ON jobs(kind);
CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status);
CREATE INDEX IF NOT EXISTS idx_jobs_created_at ON jobs(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_jobs_pending_running ON jobs(status) WHERE status IN ('pending', 'running');

-- =============================================================================
-- LLM Cache indexes
-- =============================================================================

CREATE INDEX IF NOT EXISTS idx_llm_cache_cache_key ON llm_cache(cache_key);
CREATE INDEX IF NOT EXISTS idx_llm_cache_task ON llm_cache(task);
CREATE INDEX IF NOT EXISTS idx_llm_cache_model ON llm_cache(model);
CREATE INDEX IF NOT EXISTS idx_llm_cache_expires_at ON llm_cache(expires_at);
CREATE INDEX IF NOT EXISTS idx_llm_cache_created_at ON llm_cache(created_at DESC);

-- =============================================================================
-- LLM Calls indexes
-- =============================================================================

CREATE INDEX IF NOT EXISTS idx_llm_calls_user_id ON llm_calls(user_id);
CREATE INDEX IF NOT EXISTS idx_llm_calls_model ON llm_calls(model);
CREATE INDEX IF NOT EXISTS idx_llm_calls_task ON llm_calls(task);
CREATE INDEX IF NOT EXISTS idx_llm_calls_status_code ON llm_calls(status_code);
CREATE INDEX IF NOT EXISTS idx_llm_calls_created_at ON llm_calls(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_llm_calls_key_id ON llm_calls(key_id);

-- =============================================================================
-- Portfolio indexes
-- =============================================================================

CREATE INDEX IF NOT EXISTS idx_portfolios_user_id ON portfolios(user_id);
CREATE INDEX IF NOT EXISTS idx_holdings_portfolio_id ON holdings(portfolio_id);
CREATE INDEX IF NOT EXISTS idx_holdings_user_id ON holdings(user_id);
CREATE INDEX IF NOT EXISTS idx_holdings_ticker ON holdings(ticker);
CREATE INDEX IF NOT EXISTS idx_transactions_portfolio_id ON transactions(portfolio_id);
CREATE INDEX IF NOT EXISTS idx_transactions_user_id ON transactions(user_id);
CREATE INDEX IF NOT EXISTS idx_transactions_holding_id ON transactions(holding_id);
CREATE INDEX IF NOT EXISTS idx_transactions_trade_date ON transactions(trade_date);
CREATE INDEX IF NOT EXISTS idx_transactions_ticker ON transactions(ticker);

-- =============================================================================
-- Price history indexes
-- =============================================================================

CREATE INDEX IF NOT EXISTS idx_price_history_ticker_date ON price_history(ticker, date DESC);
CREATE INDEX IF NOT EXISTS idx_price_history_ticker_exchange_date ON price_history(ticker, exchange, date DESC);
CREATE INDEX IF NOT EXISTS idx_price_history_date ON price_history(date DESC);

-- =============================================================================
-- Review queue indexes
-- =============================================================================

CREATE INDEX IF NOT EXISTS idx_review_queue_company_id ON review_queue(company_id);
CREATE INDEX IF NOT EXISTS idx_review_queue_user_id ON review_queue(user_id);
CREATE INDEX IF NOT EXISTS idx_review_queue_status ON review_queue(status);
CREATE INDEX IF NOT EXISTS idx_review_queue_document_id ON review_queue(document_id);

-- =============================================================================
-- Narrative snippets indexes
-- =============================================================================

CREATE INDEX IF NOT EXISTS idx_narrative_snippets_company_id ON narrative_snippets(company_id);
CREATE INDEX IF NOT EXISTS idx_narrative_snippets_document_id ON narrative_snippets(document_id);
CREATE INDEX IF NOT EXISTS idx_narrative_snippets_section ON narrative_snippets(section);

-- =============================================================================
-- Partial indexes for common filters
-- =============================================================================

-- Only active companies
CREATE INDEX IF NOT EXISTS idx_companies_active ON companies(user_id) WHERE is_active = true;

-- Only completed documents
CREATE INDEX IF NOT EXISTS idx_documents_completed ON documents(company_id, type) WHERE status = 'completed';

-- Only high confidence facts
CREATE INDEX IF NOT EXISTS idx_facts_high_confidence ON facts(company_id, statement, line_item, period) WHERE confidence >= 0.8;

-- Only pending/running jobs
CREATE INDEX IF NOT EXISTS idx_jobs_active ON jobs(user_id, kind) WHERE status IN ('pending', 'running');

-- =============================================================================
-- GIN indexes for JSONB columns
-- =============================================================================

CREATE INDEX IF NOT EXISTS idx_documents_meta_gin ON documents USING GIN(meta);
CREATE INDEX IF NOT EXISTS idx_facts_meta_gin ON facts USING GIN(meta);
CREATE INDEX IF NOT EXISTS idx_reports_ui_config_gin ON reports USING GIN(ui_config);
CREATE INDEX IF NOT EXISTS idx_reports_meta_gin ON reports USING GIN(meta);
CREATE INDEX IF NOT EXISTS idx_jobs_payload_gin ON jobs USING GIN(payload);
CREATE INDEX IF NOT EXISTS idx_jobs_result_gin ON jobs USING GIN(result);

-- =============================================================================
-- Statistics update (run periodically)
-- =============================================================================

-- ANALYZE; -- Run manually after bulk loads