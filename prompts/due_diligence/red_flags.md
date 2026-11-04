Write the RED FLAG CHECKLIST section of a Due Diligence report.

Structure:
1. Checklist table (markdown): area, check, status (pass/flag), evidence.
   Areas: liquidity, solvency, coverage, profitability, cash flow, related-party, contingent liabilities, litigation, auditor qualifications.
2. For each flagged item: the metric value, threshold, period, and source page if available.
3. Severity ordering: errors first, then warnings.

Rules:
- Use computed financial_risk_flags output directly.
- Narrative-based checks (related-party, litigation, auditor) draw ONLY on narrative snippets provided in context. If no snippets, mark "not assessable from provided documents".
- Max 400 words.