-- FinGen v2 — Database Migrations
-- Run in order: 001_init.sql, 002_rls.sql, 003_indexes.sql

-- =============================================================================
-- 001_init.sql — Core Tables
-- =============================================================================

-- Enable UUID extension
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- Companies table
CREATE TABLE IF NOT EXISTS companies (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    ticker TEXT,
    exchange TEXT,           -- NSE, BSE, NYSE, etc.
    currency TEXT DEFAULT 'INR',
    unit TEXT DEFAULT 'crore', -- crore, lakh, million, billion
    sector TEXT,
    industry TEXT,
    is_active BOOLEAN DEFAULT true,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(user_id, ticker)
);

-- Documents table
CREATE TABLE IF NOT EXISTS documents (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    company_id UUID NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
    user_id UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    type TEXT NOT NULL, -- annual_report, results_pr, transcript, drhp, screener_xlsx, industry_report, other
    fiscal_year TEXT,   -- FY24, FY25, etc.
    period_end DATE,    -- Actual period end date if known
    storage_path TEXT NOT NULL, -- Supabase Storage path
    file_name TEXT NOT NULL,
    file_size BIGINT,
    mime_type TEXT,
    sha256 TEXT,        -- For deduplication
    status TEXT DEFAULT 'uploaded', -- uploaded, processing, completed, failed
    page_count INT,
    error_message TEXT,
    meta JSONB DEFAULT '{}', -- Flexible metadata (parser version, etc.)
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Facts table (canonical financial facts)
CREATE TABLE IF NOT EXISTS facts (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    company_id UUID NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
    user_id UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    document_id UUID REFERENCES documents(id) ON DELETE SET NULL,
    statement TEXT NOT NULL, -- IS, BS, CF, SEGMENT, KPI, GUIDANCE
    line_item TEXT NOT NULL, -- Normalized taxonomy key (e.g., revenue_from_operations)
    raw_label TEXT,          -- Original label from source
    period TEXT NOT NULL,    -- FY24, Q1FY25, 2024-03-31, etc.
    period_type TEXT,        -- FY, Q, TTM, YTD
    value NUMERIC NOT NULL,
    unit TEXT NOT NULL,      -- INR_cr, INR_lakh, INR, USD_mn, etc.
    scaling_factor NUMERIC DEFAULT 1, -- For unit conversion
    page INT,                -- Source page number
    confidence NUMERIC DEFAULT 1.0 CHECK (confidence >= 0 AND confidence <= 1),
    edited_by_user BOOLEAN DEFAULT FALSE,
    source_text TEXT,        -- Surrounding text for context
    meta JSONB DEFAULT '{}', -- Additional metadata
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(company_id, statement, line_item, period, unit, document_id)
);

-- Assumptions table (for forecasts, scenarios)
CREATE TABLE IF NOT EXISTS assumptions (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    company_id UUID NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
    user_id UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    scenario TEXT NOT NULL, -- bull, base, bear, custom
    driver TEXT NOT NULL,   -- revenue_growth, ebitda_margin, capex_pct_sales, etc.
    period TEXT NOT NULL,   -- FY25, FY26, etc.
    value NUMERIC NOT NULL,
    unit TEXT,              -- percentage, INR_cr, times, etc.
    rationale TEXT,         -- Why this assumption
    source_document_id UUID REFERENCES documents(id) ON DELETE SET NULL,
    source_page INT,
    is_manual BOOLEAN DEFAULT TRUE, -- True if user-entered, false if LLM-suggested
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(company_id, scenario, driver, period)
);

-- Reports table
CREATE TABLE IF NOT EXISTS reports (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    company_id UUID NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
    user_id UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    type TEXT NOT NULL, -- company_analysis, equity_research, investment_research, valuation, financial_forecast, credit_analysis, risk_analysis, due_diligence, industry_analysis, portfolio_performance
    version INT DEFAULT 1,
    title TEXT,
    markdown TEXT NOT NULL,
    storage_path_docx TEXT,
    storage_path_pdf TEXT,
    status TEXT DEFAULT 'draft', -- draft, generating, completed, failed
    ui_config JSONB DEFAULT '{}', -- tone, audience, citation, privacy, etc.
    template_version TEXT, -- Template version used
    generation_time_ms INT,
    error_message TEXT,
    meta JSONB DEFAULT '{}',
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Jobs table (async processing)
CREATE TABLE IF NOT EXISTS jobs (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    company_id UUID REFERENCES companies(id) ON DELETE SET NULL,
    kind TEXT NOT NULL, -- extract, validate, generate_report, transcribe, price_fetch
    status TEXT DEFAULT 'pending', -- pending, running, completed, failed, cancelled
    progress INT DEFAULT 0, -- 0-100
    payload JSONB NOT NULL, -- Input parameters
    result JSONB, -- Output/result
    error_message TEXT,
    started_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- LLM Cache table
CREATE TABLE IF NOT EXISTS llm_cache (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    cache_key TEXT NOT NULL UNIQUE, -- SHA256 hash of task+messages+schema
    task TEXT NOT NULL, -- extract, longdoc, write, verify
    model TEXT NOT NULL,
    input_hash TEXT NOT NULL, -- Hash of input for debugging
    output JSONB NOT NULL,
    tokens_prompt INT,
    tokens_completion INT,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    expires_at TIMESTAMPTZ DEFAULT (NOW() + INTERVAL '30 days')
);

-- LLM Calls log table
CREATE TABLE IF NOT EXISTS llm_calls (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID REFERENCES auth.users(id) ON DELETE SET NULL,
    key_id TEXT NOT NULL, -- Last 8 chars of key
    model TEXT NOT NULL,
    task TEXT NOT NULL,
    status_code INT,
    latency_ms INT,
    tokens_prompt INT,
    tokens_completion INT,
    error_message TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- =============================================================================
-- Portfolio tables (Report #10)
-- =============================================================================

CREATE TABLE IF NOT EXISTS portfolios (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    description TEXT,
    base_currency TEXT DEFAULT 'INR',
    benchmark_ticker TEXT, -- e.g., NIFTY50, SENSEX
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(user_id, name)
);

CREATE TABLE IF NOT EXISTS holdings (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    portfolio_id UUID NOT NULL REFERENCES portfolios(id) ON DELETE CASCADE,
    user_id UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    ticker TEXT NOT NULL,
    name TEXT,
    exchange TEXT,
    quantity NUMERIC NOT NULL,
    avg_cost NUMERIC, -- Average cost per share
    cost_basis NUMERIC, -- Total cost
    current_price NUMERIC,
    current_value NUMERIC,
    unrealized_pnl NUMERIC,
    unrealized_pnl_pct NUMERIC,
    sector TEXT,
    market_cap TEXT, -- large, mid, small
    currency TEXT DEFAULT 'INR',
    last_price_update TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(portfolio_id, ticker)
);

CREATE TABLE IF NOT EXISTS transactions (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    portfolio_id UUID NOT NULL REFERENCES portfolios(id) ON DELETE CASCADE,
    user_id UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    holding_id UUID REFERENCES holdings(id) ON DELETE SET NULL,
    ticker TEXT NOT NULL,
    type TEXT NOT NULL, -- buy, sell, dividend, split, bonus, transfer_in, transfer_out
    quantity NUMERIC NOT NULL,
    price NUMERIC NOT NULL, -- Per share
    amount NUMERIC NOT NULL, -- Total amount (quantity * price + fees)
    fees NUMERIC DEFAULT 0,
    taxes NUMERIC DEFAULT 0,
    trade_date DATE NOT NULL,
    settlement_date DATE,
    currency TEXT DEFAULT 'INR',
    notes TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS price_history (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    ticker TEXT NOT NULL,
    exchange TEXT,
    date DATE NOT NULL,
    open NUMERIC,
    high NUMERIC,
    low NUMERIC,
    close NUMERIC NOT NULL,
    adjusted_close NUMERIC,
    volume BIGINT,
    currency TEXT DEFAULT 'INR',
    source TEXT DEFAULT 'yfinance', -- yfinance, nse, bse, manual
    created_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(ticker, exchange, date)
);

-- =============================================================================
-- Helper tables
-- =============================================================================

-- Review queue for unmapped line items
CREATE TABLE IF NOT EXISTS review_queue (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    company_id UUID NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
    user_id UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    document_id UUID REFERENCES documents(id) ON DELETE SET NULL,
    raw_label TEXT NOT NULL,
    statement TEXT,
    period TEXT,
    value NUMERIC,
    unit TEXT,
    page INT,
    suggested_taxonomy_key TEXT,
    status TEXT DEFAULT 'pending', -- pending, mapped, rejected
    mapped_taxonomy_key TEXT,
    reviewer_notes TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    resolved_at TIMESTAMPTZ
);

-- Narrative snippets (for DD, Risk reports)
CREATE TABLE IF NOT EXISTS narrative_snippets (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    company_id UUID NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
    user_id UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    document_id UUID REFERENCES documents(id) ON DELETE SET NULL,
    section TEXT, -- risk_factors, mda, auditor_report, corporate_governance, other
    text TEXT NOT NULL,
    page INT,
    themes TEXT[], -- Extracted themes: related_party, litigation, contingent_liability, etc.
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- =============================================================================
-- Updated at triggers
-- =============================================================================

CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ language 'plpgsql';

CREATE TRIGGER update_companies_updated_at BEFORE UPDATE ON companies FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();
CREATE TRIGGER update_documents_updated_at BEFORE UPDATE ON documents FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();
CREATE TRIGGER update_facts_updated_at BEFORE UPDATE ON facts FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();
CREATE TRIGGER update_assumptions_updated_at BEFORE UPDATE ON assumptions FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();
CREATE TRIGGER update_reports_updated_at BEFORE UPDATE ON reports FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();
CREATE TRIGGER update_jobs_updated_at BEFORE UPDATE ON jobs FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();
CREATE TRIGGER update_portfolios_updated_at BEFORE UPDATE ON portfolios FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();
CREATE TRIGGER update_holdings_updated_at BEFORE UPDATE ON holdings FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();