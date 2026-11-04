# FinGen Masterplan (CaseGen → Financial Research Engine)

**Rule #1: LLMs extract and write. Code calculates.** No LLM arithmetic, no LLM-typed Excel values.

## 1. Locked decisions

| Area | Decision |
| --- | --- |
| Base | Fork CaseGen. Keep Streamlit wizard, ingestion, Pydantic+retry, section regen, editor page |
| LLM | OpenRouter free models, task-routed, multi-key rotation, Gemini free as backup provider |
| Storage | **Supabase** (Postgres + Storage + Auth). No local files/SQLite/JSON. `st.session_state` = UI state only |
| Excel | openpyxl, real formulas, inputs blue / formulas black, LibreOffice headless recalc check |
| Outputs | .xlsx models, .docx/.pdf reports |
| Market | Indian listed cos first (₹ crore/lakh, Ind AS); global later |

## 2. Map existing CaseGen → FinGen

| CaseGen | Action |
| --- | --- |
| `pages/1_Upload_Documents.py` | KEEP. Add: company/ticker/FY fields, doc-type tag (annual report, results PR, transcript, DRHP/RHP, Screener xlsx). Uploads go to Supabase Storage |
| Docling/PyMuPDF/Pandas/BS4 ingestion | KEEP. Add table-preserving extraction (financial tables → structured rows, keep page no.) |
| Whisper | OPTIONAL. Earnings calls only. Run as job (see jobs table) |
| LangChain chunking | KEEP for narrative text only. **Do not chunk financial tables**; extract by statement section |
| `pages/2_Configure_Case_Study.py` | REPLACE → `2_Configure_Report.py`: report type(s), model type(s), horizon, currency/unit, rating framework, audience |
| Agent 1 Extractor | REWRITE schema → `FinancialStore` (section 5) |
| Agent 2 Storyteller | REPURPOSE → report Writers (equity, earnings, industry) |
| Agent 3 Analyst | REPLACE → deterministic Analytics engine (ratios, DuPont, growth, comps) + Modeler |
| Agent 4 Editor/Verifier | KEEP concept. Verification becomes number-tracing against store |
| Themes page | REPLACE → **Thesis & Assumptions** page (bull/base/bear, key drivers) |
| Page 5 Edit/Export | KEEP. Add Excel download + per-section regen |
| Local JSON/SQLite persistence | DELETE. Replace with Supabase repos |
| Docs (`implementation_plan.md`) | Update to this plan |

## 3. LLM layer (`core/llm/`)

### Routing (config-driven, models churn weekly on free tier)

`config/models.yaml`, never hardcode in agents:

```yaml
tasks:
  extract_financials:   [nvidia/nemotron-3-super-120b-a12b:free, qwen/qwen3.8-27b:free, openrouter/free]
  long_doc_summarise:   [nvidia/nemotron-3.5-lightning:free, qwen/qwen3.8-27b:free]   # 1M ctx
  assumptions_reason:   [nvidia/nemotron-3-super-120b-a12b:free, thinkingmachines/inkling:free]
  write_report:         [qwen/qwen3.8-27b:free, google/gemma-4-31b-it:free, openrouter/free]
  verify_bias:          [google/gemma-4-31b-it:free, qwen/qwen3.8-27b:free]
fallback_provider: gemini   # separate free-tier keys
```

Verify these IDs still exist (free list changes often): call `GET /api/v1/models`, filter `:free`. Add a startup health check that drops dead IDs and logs them. Pin providers with `provider.only` for extraction so behaviour stays consistent.

### Key rotation (`core/llm/keypool.py`)

```python
import time, threading, requests

class KeyPool:
    def __init__(self, keys, cooldown=60):
        self.keys, self.cool, self.i = keys, {}, 0
        self.cooldown, self.lock = cooldown, threading.Lock()
    def get(self):
        with self.lock:
            for _ in range(len(self.keys)):
                k = self.keys[self.i % len(self.keys)]; self.i += 1
                if self.cool.get(k, 0) < time.time(): return k
            raise RuntimeError("all keys cooling down")
    def bench(self, k, secs=None):
        self.cool[k] = time.time() + (secs or self.cooldown)

def call(task, messages, schema=None, retries=3):
    for model in cfg["tasks"][task]:                 # model fallback
        for _ in range(len(pool.keys)):              # key fallback
            k = pool.get()
            r = requests.post(URL, headers={"Authorization": f"Bearer {k}"},
                              json={"model": model, "messages": messages}, timeout=120)
            if r.status_code in (429, 402, 401, 403): pool.bench(k, 3600 if r.status_code in (401,402) else 60); continue
            if r.status_code >= 500: break           # next model
            out = r.json()["choices"][0]["message"]["content"]
            if schema: out = validate_or_repair(out, schema, retries)  # Pydantic retry w/ error fed back
            return out
    raise LLMExhausted(task)
```

Keys come from `st.secrets["OPENROUTER_KEYS"]` (list). Add: usage counter per key/model to Supabase `llm_calls` (for daily-limit awareness), exponential backoff, JSON-mode/structured-output where the model supports it.

**Caveat:** free tiers have tight daily limits and rate caps. Cache every LLM result in Supabase keyed by `hash(task+input)`, so reruns cost zero.

## 4. Storage (Supabase)

**Postgres tables**

```
users (Supabase Auth)            companies(id, user_id, name, ticker, exchange, currency, unit)
documents(id, company_id, type, fiscal_year, storage_path, status, sha256)
financial_values(id, company_id, statement, line_item, period, value, unit, currency,
                 source_doc_id, page, confidence, verified bool, edited_by_user bool)
kpis / guidance / segments   (same shape as financial_values)
assumptions(id, company_id, scenario, driver, period, value, rationale, source)
models(id, company_id, type, version, storage_path, params jsonb)
reports(id, company_id, type, version, markdown, storage_path, status)
jobs(id, user_id, kind, status, progress, payload jsonb, result jsonb)   # replaces threads
llm_cache(hash, task, model, output jsonb)   llm_calls(ts, key_id, model, task, status)
```

**Storage buckets:** `uploads/`, `models/` (xlsx), `reports/` (docx/pdf). Private, signed URLs for download. **Security:** Row Level Security on every table (`user_id = auth.uid()`). Service key only server-side in `st.secrets`. Login via Supabase Auth (email/Google). **Code:** `core/db/` repository classes (`CompanyRepo`, `FinancialRepo`, `ReportRepo`...) so no page touches SQL. Migrations in `db/migrations/*.sql`. **Long tasks:** Whisper/extraction run as `jobs` rows processed by a worker thread now (Streamlit-safe); later move to a separate worker service. Page polls job status, so refresh no longer loses work.

## 5. Canonical schema (`core/schema.py`)

```python
class Fact(BaseModel):
    line_item: str            # normalised key e.g. "revenue_from_operations"
    period: str               # "FY24", "Q2FY25"
    value: float
    unit: Literal["INR_cr","INR_lakh","INR","USD_mn",...]
    statement: Literal["IS","BS","CF","SEGMENT","KPI","GUIDANCE"]
    source_doc: str; page: int | None; confidence: float
class FinancialStore(BaseModel):
    company: Company; facts: list[Fact]
```

Ship a **line-item taxonomy** (`config/taxonomy.yaml`): \~80 canonical IS/BS/CF items with synonyms (e.g. "Total income", "Revenue from operations" → mapping). Extractor maps raw labels → taxonomy; unmapped labels go to a review queue.

## 6. Validation (pure code, `core/validate.py`)

Blocking: Assets = Liabilities + Equity; CF closing cash = BS cash; PAT ties IS↔CF; subtotals sum. Warning: YoY swings >X%, unit mismatches, missing periods. Results shown in a **Review Grid** (`st.data_editor`), edits saved with `edited_by_user=true`. Pipeline can't proceed on blocking errors.

## 7. Modeling engine (`core/models/`)

Assumptions agent proposes drivers with rationale → user edits → builder writes workbook.

| Priority | Workbook | Sheets |
| --- | --- | --- |
| P1 | 3-Statement | Inputs, IS, BS, CF, Schedules (WC, capex/D&A, debt), Checks |
| P1 | DCF | WACC, FCFF, TV (Gordon + exit multiple), sensitivity grids, equity bridge |
| P1 | Ratios | Profitability, leverage, efficiency, DuPont, common-size |
| P2 | Scenarios | Bull/base/bear switch cell |
| P2 | Comps | Peer multiples, implied valuation |
| P3 | Segment build, SOTP, LBO |  |

Standards: historicals hardcoded from store (blue), projections formulas only, checks sheet all zero, no circularity unless toggled, named ranges. After build: LibreOffice headless recalc → scan for `#REF!/#DIV/0!` → fail build if found.

## 8. Reports (`core/reports/`)

Templates in `templates/*.json` (sections, word limits, required data). Writers receive **only** store facts + computed analytics + assumptions.

- **Equity research:** summary/rating/TP, thesis, business, industry, financials, valuation, risks, catalysts
- **Earnings analysis:** actual vs prior period/estimates, driver breakdown, margin bridge, guidance delta, call takeaways
- **Industry report:** size/growth, drivers, structure, peer benchmark, outlook
- Charts: matplotlib → embedded in docx/pdf. Verifier: regex-extract every number in text → must match store/analytics within rounding, else flagged inline. Assumption-based figures labelled "estimate".

## 9. Target structure

```
fingen/
  app.py  pages/{1_Upload,2_Configure,3_Review_Data,4_Thesis_Assumptions,5_Models,6_Reports,7_Library}.py
  core/{llm/,db/,ingest/,extract/,validate.py,analytics/,models/,reports/,export/}
  config/{models.yaml,taxonomy.yaml}
  templates/  db/migrations/  tests/{fixtures/  # 3 real cos with known values}
```

## 10. Phases (each ends with a demo + tests)

| Phase | Deliverable | Done when |
| --- | --- | --- |
| **0 Foundation (2d)** | Fork, restructure, Supabase project, migrations, auth, repos, KeyPool + router, secrets | Login works; upload persists in Supabase; LLM call rotates keys on forced 429 |
| **1 Extract+Validate (5-7d)** | Taxonomy, extractor, validator, review grid | 3 test companies extract at ≥95% match on key lines; balance check passes |
| **2 Models (7-10d)** | 3-stmt + DCF + ratios .xlsx | Opens in Excel with no errors; changing an input flows through; checks = 0 |
| **3 Reports (5-7d)** | Equity + earnings writers, verifier, docx/pdf | Report numbers 100% trace to store |
| **4 Expand (ongoing)** | Industry report, comps (yfinance/NSE), scenarios, transcripts, XBRL/Screener import |  |

## 11. Risks

1. Free-tier limits/model churn → config routing, caching, cooldown keys. Plan a cheap paid fallback for extraction, since it's the accuracy-critical step.
2. PDF table extraction errors → prefer Screener/Excel/XBRL input when available; always human review grid.
3. Forecast credibility → assumptions visible, editable, sourced.
4. Sharing outputs publicly → SEBI research-analyst rules and disclaimers.

## 12. Kickoff prompt for the coding agent

> Read this plan. Inspect the repo. Do Phase 0: (1) restructure per section 9, keeping existing ingestion and pages working; (2) add Supabase client + migrations from section 4 + repo classes; (3) implement `core/llm/keypool.py` and `router.py` per section 3 with `config/models.yaml`; (4) replace all local JSON/SQLite persistence with repos; (5) add tests with a mocked 429. Stop after Phase 0 and report.