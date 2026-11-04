# FinGen v2 — Implementation Plan

**Scope:** CaseGen → FinGen v2 ("10 Reports, One Engine"). v2 supersedes v1 — **no Excel models**, template-driven engine, 3 agents (Extractor, Writer, Verifier).

**Rule:** *LLMs extract and write. Code calculates.* Every number in a report comes from the fact store or a Python analytics function.

**Deferred issues resolved in this plan:**
- **#5 (stale model IDs):** Solved by `core/llm/discover_models.py` — live discovery from OpenRouter API, 24h cache, drops dead IDs, updates `config/models.yaml` at startup. Nemotron 3 Ultra is the pinned primary for extraction.
- **#6 (KeyPool bug):** Solved by rewritten `core/llm/keypool.py` — round-robin rotation, on 429/5xx → 60s cooldown, on 401/402 → 1h exhaustion, paid fallback key, queue+timeout instead of `RuntimeError`, distributed locking via Supabase advisory locks.
- **#9 (template↔analytics contract):** Solved by `core/analytics/registry.py` — every analytics function registered with `requires` (taxonomy keys), `returns`, `period_alignment`, `output_unit`. Templates reference by name; runner validates at load time. **Decision: build everything first, wire templates last** (before testing).

---

## Folder Layout (v2 §7)

```
app.py  pages/{1_Upload,2_Configure,3_Review_Data,4_Generate,5_Edit_Export,6_Library}.py
core/{llm/,db/,ingest/,extract/,validate.py,analytics/,generate/,verify/,export/,jobs/}
core/analytics/{growth,ratios,credit,valuation,forecast,risk,industry,portfolio,charts,registry}.py
templates/reports/*.json   prompts/<report>/<section>.md   config/{models.yaml,taxonomy.yaml}
db/migrations/  tests/fixtures/  (3 real companies with known values)
```

---

## Phase 0: Foundation (Week 1)

| Task | Deliverable | Done when |
|---|---|---|
| F0-01 | Repo restructure + `config/models.yaml` | Folder matches layout above |
| F0-02 | Supabase project + `db/migrations/001-003.sql` (tables, RLS, indexes) | 13 tables live, RLS on |
| F0-03 | Repo layer: `core/db/repos/` (base, company, document, fact, assumption, report, job, llm_cache, llm_calls, portfolio) | CRUD works per table |
| F0-04 | LLM layer: `discover_models.py` + `keypool.py` + `router.py` | Forced 429 rotates key; paid fallback works; discovery caches |
| F0-05 | Auth (Supabase Auth) + session bridge; **delete** local JSON/SQLite/`session_backup` | Login required; zero local persistence |
| F0-06 | Ingestion → Supabase Storage (`uploads/{user_id}/{doc_id}/`); doc-type classifier | Files in Storage, `documents` rows created |
| F0-07 | Spreadsheet parser → `Fact` rows directly (**bypass chunker**) | Facts in DB with taxonomy keys |
| F0-08 | Chunker → **narrative text only** (MD&A, risk factors, transcripts) | Chunks stored with `document_id` tags |
| F0-09 | Mocked-429 integration test | Test passes |

**Phase 0 done when:** Upload persists to Supabase; `documents` row created; LLM call rotates keys on forced 429; no local files written.

---

## Phase 1: Extract + Validate (Weeks 2-3)

| Task | Deliverable | Done when |
|---|---|---|
| F1-01 | `core/schema.py` (Fact model) + `config/taxonomy.yaml` (~80 IS/BS/CF items with synonyms) | Schema matches §5; unmapped labels → review queue |
| F1-02 | `core/extract/extractor.py` — **section-based** extraction (not chunked); maps raw labels → taxonomy; narrative snippets separate | 3 test cos extract cleanly |
| F1-03 | `core/validate.py` — pure code. **Blocking:** Assets=L+E, CF closing cash=BS cash, PAT ties IS↔CF, subtotals sum. **Warning:** YoY swing >50%, unit mismatch, period gap | Validation gates work |
| F1-04 | `pages/3_Review_Data.py` — `st.data_editor` grid (rows=taxonomy items, cols=periods); edit → `edited_by_user=true`; **"Proceed" disabled until blocking=[]** | Grid editable, blocks pipeline until clean |
| F1-05 | `pages/4_Thesis_Assumptions.py` — bull/base/bear driver grid (revenue growth, EBITDA margin, capex%, WACC…) with rationale + source | Saved to `assumptions` table |

**Phase 1 done when:** 3 test companies (Tata Steel, Toyota, +1 Indian co) extract ≥95% of key lines vs ground-truth fixtures; balance check passes.

**Ground-truth fixtures (blocker — build FIRST):**
```
tests/fixtures/{tata_steel,toyota,reliance}/
├── raw/                      # PDF, Excel, URLs
├── expected_facts.csv        # line_item, period, value, unit, statement, page
├── expected_validation.json  # blocking: [], warnings: [...]
└── expected_ratios.csv       # period, ratio_name, value
```

---

## Phase 2: Engine + First 2 Reports (Weeks 4-5)

| Task | Deliverable | Done when |
|---|---|---|
| F2-01 | `core/analytics/` — 8 modules: growth, ratios, credit, valuation, forecast, risk, industry, portfolio + `registry.py` | All functions typed, unit-tested vs fixtures |
| F2-02 | `templates/reports/*.json` (9 templates) + `prompts/<report>/<section>.md` | Templates validate against registry |
| F2-03 | `core/generate/runner.py` — template runner: load template → fetch facts → compute analytics → build prompt → LLM write → assemble | Sections stream to job progress |
| F2-04 | `core/jobs/worker.py` + `jobs` table — job-based generation, page polls every 2s | Refresh no longer loses work |
| F2-05 | `core/verify/verifier.py` — **code-first**: regex-extract every number → normalize unit → match against fact store/analytics (1% tolerance reported, 5% derived); flags: MISSING_SOURCE, MISMATCH, UNSUPPORTED_CLAIM, PROMOTIONAL_LANGUAGE; LLM second pass only on flagged segments | Catches injected errors |
| F2-06 | `core/export/` — docx/pdf + chart embedding (matplotlib → image) | Downloads work with charts |
| F2-07 | `pages/4_Generate.py` — polling UI with per-section progress bars | Live progress, done → preview |

**Phase 2 done when:** **Company Analysis** and **Equity Research** export end-to-end; report numbers 100% traceable to fact store.

---

## Phase 3: Valuation Family (Week 6)

| Task | Deliverable | Done when |
|---|---|---|
| F3-01 | `valuation.py`: DCF (WACC/FCFF/TV Gordon + exit multiple), multiples, football field, sensitivity grid | DCF/multiples match hand calc |
| F3-02 | `forecast.py`: 5-yr projected IS/BS/CF from assumptions | Scenarios flow through |
| F3-03 | Templates: Valuation, Financial Forecast, Investment Research | 3 reports generate |

---

## Phase 4: Risk Family (Week 7)

| Task | Deliverable | Done when |
|---|---|---|
| F4-01 | `credit.py` (rating, ICR/DSCR, Altman, covenant headroom), `risk.py` (financial/operational/market flags), `dd.py` (related-party, contingent liabilities, auditor notes, litigation) | Flags cite source pages |
| F4-02 | Templates: Credit Analysis, Risk Analysis, Due Diligence | 3 reports generate |

---

## Phase 5: Doc-Heavy (Week 8)

| Task | Deliverable | Done when |
|---|---|---|
| F5-01 | Peer ingestion (yfinance/Screener API) → peer `facts` rows; `industry.py` (market size/growth, peer benchmark, HHI concentration) | Peer benchmark table renders |
| F5-02 | Industry Analysis template (long-context via `longdoc` task) | Report generates |

---

## Phase 6: Portfolio (Week 9) — **separate mini-pipeline**

| Task | Deliverable | Done when |
|---|---|---|
| F6-01 | CSV holdings import; price fetch (yfinance + NSEpy); `portfolio.py` (XIRR, allocation, attribution, drawdown, benchmark) | XIRR matches reference calc |
| F6-02 | Portfolio Performance template; Page 3 shows holdings grid instead of fact grid | Report generates |

---

## Phase 7: Library + Polish (Week 10)

| Task | Deliverable | Done when |
|---|---|---|
| F7-01 | `pages/6_Library.py` — report versions, view/download/regenerate/delete | Library works |
| F7-02 | Disclaimers (SEBI RA rules for equity/valuation/credit reports), financial citations ("Source: Company AR FY24, p.42"), data-privacy masking toggle, E2E test all 10 reports | 10 reports green |

---

## Workflow (end-to-end)

```
Upload → Extract facts → Validate (code) → Review grid
      → Thesis & Assumptions (bull/base/bear)
      → Analytics engine (code) → Report Generator (template + LLM)
      → Verifier (code-first) → Edit → Export docx/pdf
```

**Template example:**
```json
{
  "id": "credit_analysis",
  "sections": [
    {"key": "leverage", "analytics": ["debt_equity","net_debt_ebitda"],
     "needs": ["BS.total_debt","BS.total_equity","BS.cash_and_equivalents","IS.ebitda"],
     "prompt": "credit/leverage.md", "max_words": 250, "chart": "leverage_trend"}
  ]
}
```

**Runner flow per section:** `registry.get_spec(analytics)` → `spec.validate_facts_available(facts)` → `AnalyticsExecutor.execute()` → build prompt with metrics → `router.call(TaskType.WRITE, ...)` → verifier.

---

## Critical Path

```
F0-02 → F0-03 → F0-04 → F1-01 → F1-02 → F1-03 → F1-04 → F2-01 → F2-02 → F2-03 → F2-05 → F2-07
```

**Parallel tracks:** F0-01/F0-05 from Day 1; F2-01 (analytics) after F1-01 (schema known); F3-F6 after F2-07 (engine proven).

---

## Explicitly NOT in scope (v1 features removed by v2)

3-statement Excel model · DCF workbook · LibreOffice recalc · scenario switch cell · Excel comps sheet · SOTP/LBO workbooks · themes page · local JSON/SQLite persistence · 4-agent structure (now 3) · PDF table chunking.

---

## Implementation Status (as of writing)

| Module | Status |
|---|---|
| `config/models.yaml` | ✅ written |
| `core/llm/keypool.py` (issue #6 fix) | ✅ written |
| `core/llm/discover_models.py` (issue #5 fix) | ✅ written |
| `core/llm/router.py` | ✅ written |
| `core/db/client.py` | ✅ written |
| `core/schema.py` (Fact model + unit conversion) | ✅ written |
| `db/migrations/001_init.sql` | ✅ written |
| `db/migrations/002_rls.sql` | ✅ written |
| `db/migrations/003_indexes.sql` | ✅ written |
| `core/db/repos/` (8 repos) | ✅ written |
| `core/analytics/registry.py` (issue #9 foundation) | ✅ written |
| `core/analytics/growth.py` | ✅ written |
| `core/analytics/ratios.py` | ✅ written |
| `core/analytics/credit.py` | ✅ written |
| `core/analytics/valuation.py` | ✅ written |
| `core/analytics/forecast.py` | ✅ written |
| `core/analytics/risk.py` | ⬜ TODO |
| `core/analytics/industry.py` | ⬜ TODO |
| `core/analytics/portfolio.py` | ⬜ TODO |
| `core/analytics/charts.py` | ⬜ TODO |
| `core/extract/extractor.py` | ⬜ TODO |
| `core/validate.py` | ⬜ TODO |
| `core/generate/runner.py` | ⬜ TODO |
| `core/verify/verifier.py` | ⬜ TODO |
| `core/export/` | ⬜ TODO |
| `core/jobs/worker.py` | ⬜ TODO |
| `core/ingest/` (adapted from CaseGen) | ⬜ TODO |
| `config/taxonomy.yaml` | ⬜ TODO |
| `templates/reports/*.json` (9) | ⬜ TODO |
| `prompts/**/*.md` | ⬜ TODO |
| `pages/` (6 pages) | ⬜ TODO |
| `app.py` / `Home.py` | ⬜ TODO |
| `requirements.txt` (updated) | ⬜ TODO |
| `tests/fixtures/` (3 companies) | ⬜ TODO |

**Next in build order:** `config/taxonomy.yaml` → `core/extract/extractor.py` → `core/validate.py` → remaining analytics (risk/industry/portfolio/charts) → `runner.py` + `worker.py` → `verifier.py` → `export/` → templates + prompts → pages → `app.py`.
