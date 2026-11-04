# FinGen Plan v2: 10 Reports, One Engine

Supersedes v1 scope. **No Excel models.** Kept from v1: OpenRouter task routing + KeyPool rotation (v1 §3), Supabase storage (v1 §4), canonical fact schema + validator (v1 §5-6).

**Rule: LLMs extract and write. Code calculates.** Every number in a report comes from the fact store or a Python analytics function.

## 1. Reports

| # | Report | Inputs | Analytics (code) |
| --- | --- | --- | --- |
| 1 | Company Analysis | Annual report, results | Growth, margins, ratios, DuPont, segment mix |
| 2 | Equity Research | Same + price | #1 + valuation summary, rating, target price |
| 3 | Investment Research | Same + market data | Thesis, bull/base/bear, risk/reward |
| 4 | Valuation | Same + peers | DCF, multiples, football-field, sensitivity (as tables/charts) |
| 5 | Financial Forecast / Projection | Historicals + assumptions | 3-5yr projection of IS/BS/CF, scenario table |
| 6 | Credit Analysis | Financials, debt schedule | Leverage, ICR/DSCR, liquidity, Altman-style score, internal rating |
| 7 | Risk Analysis | Financials, news | Financial/operational/market risk flags, volatility, sensitivity |
| 8 | Due Diligence | Any docs (RHP/DRHP, contracts, filings) | Red-flag checklist: related-party, contingent liabilities, auditor notes, litigation |
| 9 | Industry Analysis | Industry reports, URLs, peers' financials | Market size/growth, peer benchmarking, concentration |
| 10 | Portfolio Performance | Holdings/transactions CSV + prices | Returns, XIRR, allocation, vs benchmark, drawdown, attribution |

**#10 is the odd one out.** It ingests holdings, not company filings. Build last as its own mini-pipeline.

## 2. Architecture (one pipeline, template-driven)

```
Upload → Extract facts → Validate (code) → Review grid
      → Analytics engine (code) → Report Generator (template + LLM) → Verifier → Edit → Export docx/pdf
```

**One generic engine; each report is a JSON template**, not a separate agent:

```json
{
  "id": "credit_analysis",
  "sections": [
    {"key": "leverage", "analytics": ["debt_equity","net_debt_ebitda"], "needs": ["BS.debt","IS.ebitda"],
     "prompt": "credit/leverage.md", "max_words": 250, "chart": "leverage_trend"},
    ...
  ]
}
```

Adding a report = new template + any missing analytics function. No new pipeline code.

## 3. Agents (down from 4 to 3)

| Agent | Job |
| --- | --- |
| Extractor (LLM) | Docs → `Fact` rows with source page (v1 §5). Also pulls narrative snippets (risk factors, MD&A, auditor notes) for DD/risk |
| Writer (LLM) | Per section: gets only that section's facts + computed metrics + assumptions → prose. Section-level regenerate |
| Verifier (code first, LLM second) | Regex every number in text → must match store/analytics; flags unsupported claims; neutralises promotional language |

Analytics, validation, charts, and export are plain code.

## 4. Model routing (`config/models.yaml`, same KeyPool as v1)

```yaml
extract:  [nvidia/nemotron-3-super-120b-a12b:free, qwen/qwen3.8-27b:free, openrouter/free]
longdoc:  [nvidia/nemotron-3.5-lightning:free, qwen/qwen3.8-27b:free]      # DD, industry
write:    [qwen/qwen3.8-27b:free, google/gemma-4-31b-it:free, openrouter/free]
verify:   [google/gemma-4-31b-it:free, qwen/qwen3.8-27b:free]
```

Confirm IDs against OpenRouter's live `:free` list at startup; drop dead ones. Cache all LLM outputs in Supabase.

## 5. Supabase (trimmed)

`companies, documents, facts, assumptions, reports(type, version, sections jsonb, markdown, file_path), jobs, llm_cache, llm_calls` + `portfolios, holdings, transactions` (for #10). Buckets: `uploads/`, `reports/`. Auth + RLS on `user_id`. All DB access via `core/db/` repos. `st.session_state` holds UI state only.

## 6. Pages (5 + library)

1. **Upload**: company/ticker/FY, doc type tags, files → Storage (existing page, extended)
2. **Configure**: pick report type (drives template), audience, tone, privacy masking, citation format
3. **Review Data**: validation results + editable fact grid (skipped for Portfolio; shows holdings grid)
4. **Generate**: section progress bars, runs as a job
5. **Edit & Export**: markdown editor, per-section regen, download docx/pdf
6. **Library**: past reports, versions (replaces SQLite history)

Reuse from CaseGen: ingestion, chunking (narrative only, never tables), Pydantic retry, Page 5 editor, section regen, export code, tone/audience/citation settings. Delete: themes page, local JSON/SQLite.

## 7. Folder layout

```
app.py  pages/{1_Upload,2_Configure,3_Review_Data,4_Generate,5_Edit_Export,6_Library}.py
core/{llm/,db/,ingest/,extract/,validate.py,analytics/,generate/,verify/,export/}
core/analytics/{growth,ratios,credit,valuation,forecast,risk,industry,portfolio}.py
templates/reports/*.json   prompts/<report>/<section>.md   config/{models.yaml,taxonomy.yaml}
tests/fixtures/  (3 real companies with known values)
```

## 8. Build order

| Phase | Ship | Done when |
| --- | --- | --- |
| 0 Foundation (2d) | Restructure, Supabase + auth + repos, KeyPool/router | Upload persists in cloud; forced 429 rotates key |
| 1 Extract + Validate (5-7d) | Taxonomy, extractor, validator, review grid | 3 test cos ≥95% match on key lines; balance sheet ties |
| 2 Engine + first 2 reports (5-7d) | Template runner, ratios/growth, verifier, docx/pdf | **Company Analysis** and **Equity Research** export with 100% traceable numbers |
| 3 Valuation family (5d) | valuation.py, forecast.py → Valuation, Forecast, Investment Research | DCF/multiples tables match hand calc |
| 4 Risk family (5d) | credit.py, risk.py → Credit, Risk | Scores reproducible; flags cite source pages |
| 5 Doc-heavy (5d) | Due Diligence, Industry (long-context, URL/peer ingestion) | Every red flag links to a page |
| 6 Portfolio (4d) | CSV import, prices (yfinance), portfolio.py, report | XIRR matches reference calc |

Order rationale: reports 1-7 share the same fact store, so each new one is mostly a template + analytics function.

## 9. Risks

- **Extraction accuracy** is the foundation. Prefer Screener/Excel exports over PDF where possible; keep the review grid mandatory.
- **Free-tier limits**: caching + key cooldowns; plan a cheap paid model for extraction if quality/quotas bite.
- **Rating / target price / DD conclusions** are judgment calls. Show inputs and mark them "analyst-review required"; add disclaimers if shared (SEBI RA rules).
- **Industry/DD** depend on source quality; the verifier must cite documents, and unsupported claims are dropped.

## 10. Kickoff prompt for the coding agent

> Read this plan and v1 §3-6. Inspect the repo. Do Phase 0 only: restructure per §7 keeping existing ingestion/pages working; add Supabase client, migrations (§5), and repo classes; implement `core/llm/keypool.py` + `router.py` with `config/models.yaml`; remove local JSON/SQLite persistence; add a mocked-429 test. Stop and report.