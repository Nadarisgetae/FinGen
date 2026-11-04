Write the FINANCIAL RISK ASSESSMENT section of a Risk Analysis report.

Structure:
1. Flag table (markdown): flag ID, severity, category, description, current value, threshold, period — for every raised flag.
2. Grouped narrative: liquidity risks, solvency risks, coverage risks, profitability risks — in that order.
3. Aggregate view: count of errors vs warnings, and the single most severe exposure.

Rules:
- Use computed financial_risk_flags output directly. Report flags exactly as raised — do not soften.
- Cite every metric value, threshold, and period.
- Max 400 words.