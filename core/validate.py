"""
FinGen v2 — Validator (Pure Code, No LLM)
Blocking checks gate the pipeline. Warnings are informational.
"""

import logging
from typing import Dict, List, Optional
from collections import defaultdict

from core.schema import Fact, ValidationResult

logger = logging.getLogger(__name__)

# Tolerance for floating point comparisons
TOLERANCE = 0.005  # 0.5%


class Validator:
    """
    Validates extracted facts with deterministic accounting checks.

    Blocking (pipeline cannot proceed):
    - BS.balance: Assets = Liabilities + Equity
    - CF.cash_tie: CF closing cash = BS cash
    - IS_CF.pat_tie: IS PAT ≈ CF PAT
    - Subtotal.sums: line items sum to stated subtotals

    Warning (informational):
    - YoY swing > 50%
    - Unit mismatches across periods
    - Missing periods
    """

    def __init__(self, facts: List[Fact]):
        self.facts = facts
        self._by_period: Dict[str, Dict[str, Fact]] = defaultdict(dict)
        self._by_statement: Dict[str, Dict[str, Dict[str, Fact]]] = defaultdict(lambda: defaultdict(dict))
        self._periods: List[str] = []

        for f in facts:
            self._by_period[f.period][f.line_item] = f
            self._by_statement[f.statement][f.period][f.line_item] = f
            if f.period not in self._periods:
                self._periods.append(f.period)

        self._periods.sort()

    def validate(self) -> ValidationResult:
        blocking = []
        warnings = []

        # --- Blocking checks ---
        blocking.extend(self._check_balance_sheet())
        blocking.extend(self._check_cash_tie())
        blocking.extend(self._check_pat_tie())
        blocking.extend(self._check_subtotals())

        # --- Warning checks ---
        warnings.extend(self._check_yoy_swings())
        warnings.extend(self._check_unit_mismatch())
        warnings.extend(self._check_missing_periods())
        warnings.extend(self._check_negative_revenue())

        return ValidationResult(blocking=blocking, warnings=warnings)

    # =============================================================================
    # BLOCKING CHECKS
    # =============================================================================

    def _check_balance_sheet(self) -> List[str]:
        """Assets = Liabilities + Equity (per period)."""
        errors = []
        bs = self._by_statement.get("BS", {})

        for period in sorted(bs.keys()):
            period_facts = bs[period]
            total_assets = self._val(period_facts, "total_assets")
            total_liabilities = self._val(period_facts, "total_liabilities")
            total_equity = self._val(period_facts, "total_equity")

            if total_assets is None:
                continue  # No total stated — skip (can't check)
            if total_liabilities is None or total_equity is None:
                # Try to compute from components
                current_liab = self._val(period_facts, "current_liabilities")
                noncurrent_liab = self._val(period_facts, "non_current_liabilities")
                if current_liab is not None and noncurrent_liab is not None:
                    total_liabilities = current_liab + noncurrent_liab
                share_cap = self._val(period_facts, "share_capital")
                reserves = self._val(period_facts, "reserves_and_surplus")
                if total_equity is None and share_cap is not None and reserves is not None:
                    total_equity = share_cap + reserves
                if total_liabilities is None or total_equity is None:
                    continue

            lhs = total_assets
            rhs = total_liabilities + total_equity
            if abs(lhs - rhs) > max(abs(lhs) * TOLERANCE, 0.01):
                errors.append(
                    f"BS.balance [{period}]: Assets {lhs:,.2f} ≠ Liabilities+Equity {rhs:,.2f} "
                    f"(diff {lhs - rhs:,.2f})"
                )
        return errors

    def _check_cash_tie(self) -> List[str]:
        """CF closing cash = BS cash (per period)."""
        errors = []
        cf = self._by_statement.get("CF", {})
        bs = self._by_statement.get("BS", {})

        for period in sorted(cf.keys()):
            closing_cash = self._val(cf[period], "closing_cash")
            bs_cash = self._val(bs.get(period, {}), "cash_and_equivalents")
            if closing_cash is None or bs_cash is None:
                continue
            if abs(closing_cash - bs_cash) > max(abs(closing_cash) * TOLERANCE, 0.01):
                errors.append(
                    f"CF.cash_tie [{period}]: CF closing cash {closing_cash:,.2f} ≠ BS cash {bs_cash:,.2f}"
                )
        return errors

    def _check_pat_tie(self) -> List[str]:
        """IS PAT ≈ CF PAT (per period)."""
        errors = []
        is_facts = self._by_statement.get("IS", {})
        cf = self._by_statement.get("CF", {})

        for period in sorted(is_facts.keys()):
            is_pat = self._val(is_facts[period], "profit_after_tax")
            # CF PAT often embedded in CFO start line; check via cfo if pat missing
            cf_pat = self._val(cf.get(period, {}), "profit_after_tax")
            if is_pat is None or cf_pat is None:
                continue
            if abs(is_pat - cf_pat) > max(abs(is_pat) * TOLERANCE, 0.01):
                errors.append(
                    f"IS_CF.pat_tie [{period}]: IS PAT {is_pat:,.2f} ≠ CF PAT {cf_pat:,.2f}"
                )
        return errors

    def _check_subtotals(self) -> List[str]:
        """Line items sum to stated subtotals."""
        errors = []

        # IS: Revenue = core revenue (+ other income for total_income)
        # IS: PBT = EBIT - finance costs (+/- exceptional)
        # IS: PAT = PBT - tax
        is_facts = self._by_statement.get("IS", {})
        for period in sorted(is_facts.keys()):
            pf = is_facts[period]

            # PAT = PBT - tax
            pbt = self._val(pf, "profit_before_tax")
            tax = self._val(pf, "tax_expense")
            pat = self._val(pf, "profit_after_tax")
            if pbt is not None and tax is not None and pat is not None:
                expected = pbt - tax
                if abs(expected - pat) > max(abs(expected) * TOLERANCE, 0.01):
                    errors.append(
                        f"Subtotal.IS.pat [{period}]: PBT {pbt:,.2f} - Tax {tax:,.2f} = {expected:,.2f} ≠ PAT {pat:,.2f}"
                    )

            # PBT = EBIT - finance costs (+ exceptional items)
            ebit = self._val(pf, "ebit") or self._val(pf, "operating_profit")
            finance = self._val(pf, "finance_costs")
            exceptional = self._val(pf, "exceptional_items") or 0.0
            if ebit is not None and finance is not None and pbt is not None:
                expected = ebit - finance - exceptional
                if abs(expected - pbt) > max(abs(expected) * TOLERANCE, 0.01):
                    errors.append(
                        f"Subtotal.IS.pbt [{period}]: EBIT {ebit:,.2f} - Finance {finance:,.2f} = {expected:,.2f} ≠ PBT {pbt:,.2f}"
                    )

        # BS: Current assets components sum
        bs_facts = self._by_statement.get("BS", {})
        for period in sorted(bs_facts.keys()):
            pf = bs_facts[period]
            total_eq = self._val(pf, "total_equity")
            share_cap = self._val(pf, "share_capital")
            reserves = self._val(pf, "reserves_and_surplus")
            if total_eq is not None and share_cap is not None and reserves is not None:
                expected = share_cap + reserves
                if abs(expected - total_eq) > max(abs(expected) * TOLERANCE, 0.01):
                    errors.append(
                        f"Subtotal.BS.equity [{period}]: Share Capital {share_cap:,.2f} + Reserves {reserves:,.2f} = {expected:,.2f} ≠ Total Equity {total_eq:,.2f}"
                    )

        return errors

    # =============================================================================
    # WARNING CHECKS
    # =============================================================================

    def _check_yoy_swings(self) -> List[str]:
        """Flag YoY swings > 50% on key items."""
        warnings = []
        key_items = ["revenue_from_operations", "profit_after_tax", "ebitda", "total_assets"]

        for item in key_items:
            series = []
            for period in self._periods:
                f = self._by_period.get(period, {}).get(item)
                if f:
                    series.append((period, f.value))

            for i in range(1, len(series)):
                prev_period, prev_val = series[i - 1]
                curr_period, curr_val = series[i]
                if prev_val != 0:
                    swing = abs(curr_val - prev_val) / abs(prev_val)
                    if swing > 0.5:
                        warnings.append(
                            f"YoY.swing [{item}] {prev_period}→{curr_period}: "
                            f"{swing * 100:.1f}% swing ({prev_val:,.2f} → {curr_val:,.2f})"
                        )
        return warnings

    def _check_unit_mismatch(self) -> List[str]:
        """Same line_item with different units across periods."""
        warnings = []
        units_by_item: Dict[str, set] = defaultdict(set)
        for f in self.facts:
            units_by_item[f.line_item].add(f.unit)

        for item, units in units_by_item.items():
            if len(units) > 1:
                warnings.append(
                    f"Unit.mismatch [{item}]: multiple units found {sorted(units)}"
                )
        return warnings

    def _check_missing_periods(self) -> List[str]:
        """Detect gaps in fiscal year sequence."""
        warnings = []
        fy_periods = [p for p in self._periods if p.upper().startswith("FY")]
        years = []
        for p in fy_periods:
            try:
                years.append(int(p[2:]))
            except ValueError:
                pass
        years = sorted(set(years))

        if len(years) >= 2:
            for i in range(1, len(years)):
                if years[i] - years[i - 1] > 1:
                    warnings.append(
                        f"Period.gap: missing FY{years[i-1] + 1} between FY{years[i-1]} and FY{years[i]}"
                    )
        return warnings

    def _check_negative_revenue(self) -> List[str]:
        """Revenue should never be negative (data quality)."""
        warnings = []
        for period in self._periods:
            rev = self._val(self._by_period.get(period, {}), "revenue_from_operations")
            if rev is not None and rev < 0:
                warnings.append(f"Data.quality [{period}]: negative revenue {rev:,.2f}")
        return warnings

    @staticmethod
    def _val(period_facts: Dict[str, Fact], line_item: str) -> Optional[float]:
        f = period_facts.get(line_item)
        return f.value if f else None


def validate_facts(facts: List[Fact]) -> ValidationResult:
    """Convenience function."""
    return Validator(facts).validate()