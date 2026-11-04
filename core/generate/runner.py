"""
FinGen v2 — Report Generator (Template Runner)

Flow:
1. Load template (JSON)
2. Validate template against analytics registry
3. For each section:
   a. Fetch required facts (FactRepo)
   b. Compute analytics (AnalyticsExecutor)
   c. Build prompt with section facts + metrics + assumptions
   d. LLM write (TaskType.WRITE)
   e. Stream progress to job
4. Assemble markdown document
5. Run verifier (code-first)
6. Save report + exports
"""

import json
import logging
import time
from pathlib import Path
from typing import Dict, List, Optional, Any, Callable

import yaml

from core.analytics.registry import (
    get_spec, validate_template_analytics, get_required_facts_for_template,
    get_executor,
)
from core.llm.router import TaskType, get_router, build_writing_prompt
from core.verify.verifier import Verifier
from core.schema import Fact

logger = logging.getLogger(__name__)

TEMPLATES_DIR = Path("templates/reports")
PROMPTS_DIR = Path("prompts")


class ReportGenerator:
    """Generates a report from a template + facts + assumptions."""

    def __init__(self, template_path: str):
        with open(template_path, encoding="utf-8") as f:
            self.template = json.load(f)

        # Validate template against registry
        errors = validate_template_analytics(self.template.get("sections", []))
        if errors:
            raise ValueError(f"Template validation failed: {errors}")

        # Load section prompts
        self.prompts = {}
        for section in self.template.get("sections", []):
            prompt_file = section.get("prompt")
            if prompt_file:
                ppath = PROMPTS_DIR / prompt_file
                if ppath.exists():
                    self.prompts[section["key"]] = ppath.read_text(encoding="utf-8")

        self.router = get_router()
        self.executor = get_executor()

    def generate(
        self,
        company_id,
        user_id,
        facts: List[Fact],
        assumptions: Dict[str, Dict] = None,
        ui_config: Dict = None,
        context: Dict = None,
        on_progress: Optional[Callable[[int, int, str], None]] = None,
    ) -> Dict[str, Any]:
        """
        Generate the full report.

        Returns: {
            "markdown": str,
            "sections": {section_key: markdown},
            "analytics_results": {section_key: {analytics_name: result}},
            "verification": VerificationResult,
        }
        """
        sections = self.template.get("sections", [])
        total = len(sections)
        section_outputs = {}
        analytics_results = {}

        for i, section in enumerate(sections):
            section_key = section["key"]
            section_title = section.get("title", section_key)

            if on_progress:
                on_progress(i, total, section_title)

            try:
                # 1. Compute analytics for this section
                section_analytics = {}
                for analytics_name in section.get("analytics", []):
                    try:
                        result = self.executor.execute(
                            analytics_name,
                            facts=facts,
                            assumptions=(assumptions or {}).get(section_key),
                            context=context,
                        )
                        section_analytics[analytics_name] = result
                    except Exception as e:
                        logger.warning(f"Analytics {analytics_name} failed: {e}")
                        section_analytics[analytics_name] = {"error": str(e)}
                analytics_results[section_key] = section_analytics

                # 2. Build prompt
                prompt_text = self.prompts.get(section_key, "")
                max_words = section.get("max_words", 500)

                # Gather section-relevant facts
                needs = section.get("needs", [])
                section_facts = [
                    f for f in facts
                    if f"{f.statement}.{f.line_item}" in needs
                ]

                system = (
                    f"You are a financial report writer.\n"
                    f"Section: {section_title}\n"
                    f"Max words: {max_words}\n"
                    f"Audience: {(ui_config or {}).get('audience', 'professional')}\n"
                    f"Tone: {(ui_config or {}).get('tone', 'objective')}\n\n"
                    f"{prompt_text}\n\n"
                    "RULES:\n"
                    "1. Use ONLY the provided facts and computed metrics. Do NOT invent numbers.\n"
                    "2. Every number must cite its period (e.g., 'FY24 revenue was ₹1,234 cr').\n"
                    "3. If a metric is unavailable, omit it entirely — do not write 'not disclosed'.\n"
                    "4. Mark assumption-derived figures as '(estimate)'.\n"
                    "5. Write in markdown. No em-dashes.\n"
                )

                user_context = {
                    "facts": [
                        {
                            "line_item": f.line_item,
                            "period": f.period,
                            "value": f.value,
                            "unit": f.unit,
                            "page": f.page,
                        }
                        for f in section_facts
                    ],
                    "analytics": {
                        name: res.metrics if hasattr(res, "metrics") else res
                        for name, res in section_analytics.items()
                    },
                    "assumptions": (assumptions or {}).get(section_key, {}),
                }

                messages = build_writing_prompt(system, f"Write the '{section_title}' section.", user_context)

                # 3. LLM write
                try:
                    content = self.router.call(TaskType.WRITE, messages)
                except Exception as e:
                    logger.error(f"LLM write failed for {section_key}: {e}")
                    content = f"_[Section generation failed: {e}]_"

                section_outputs[section_key] = content

            except Exception as e:
                logger.exception(f"Section {section_key} failed: {e}")
                section_outputs[section_key] = f"_[Section failed: {e}]_"

        # 4. Assemble document
        markdown = self._assemble(section_outputs)

        # 5. Verify (code-first)
        verifier = Verifier(facts=facts, analytics_results=analytics_results)
        verification = verifier.verify(markdown)

        if on_progress:
            on_progress(total, total, "Verification complete")

        return {
            "markdown": markdown,
            "sections": section_outputs,
            "analytics_results": {
                sk: {name: (r.metrics if hasattr(r, "metrics") else r) for name, r in ar.items()}
                for sk, ar in analytics_results.items()
            },
            "verification": verification,
        }

    def _assemble(self, section_outputs: Dict[str, str]) -> str:
        """Assemble sections into final markdown document."""
        parts = [f"# {self.template.get('title', 'Report')}\n"]

        for section in self.template.get("sections", []):
            key = section["key"]
            title = section.get("title", key)
            content = section_outputs.get(key, "")
            if content:
                # Strip any heading the LLM may have added
                import re
                content = re.sub(
                    rf"^\s*#{{1,3}}\s*{re.escape(title)}.*\n+",
                    "",
                    content,
                    flags=re.IGNORECASE,
                )
                parts.append(f"\n## {title}\n\n{content.strip()}\n")

        return "\n".join(parts)


def load_template(report_type: str) -> "ReportGenerator":
    """Load a report template by type."""
    path = TEMPLATES_DIR / f"{report_type}.json"
    if not path.exists():
        raise FileNotFoundError(f"Template not found: {path}")
    return ReportGenerator(str(path))


def list_templates() -> List[str]:
    """List available report templates."""
    if not TEMPLATES_DIR.exists():
        return []
    return [p.stem for p in TEMPLATES_DIR.glob("*.json")]