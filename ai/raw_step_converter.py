"""
Raw Step Converter — uses Azure OpenAI to convert free-form test steps
into the structured Excel template format.

Input:  test_cases_raw.xlsx  (TC_ID, Step_Order, Raw_Step)
Output: test_cases.xlsx      (TC_ID, Page, Action, Target, Value, Expected)

Uses the DOM Knowledge Base (if available) to ground element names and
page references against actual extracted UI elements.
"""
from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import List, Optional

import pandas as pd

from ai.clients.azure_openai_client import AzureOpenAIClient
from ai.config import AIConfig
from core.pages.page_registry import PAGE_REGISTRY, DYNAMIC_PAGES, get_supported_fields

logger = logging.getLogger(__name__)
ai_logger = logging.getLogger("ai_reasoning")

# ── Prompt ──────────────────────────────────────────────────────────────

_RAW_CONVERSION_PROMPT = """\
You are a test automation expert converting free-form test steps into a structured format.

REGISTERED PAGES (you MUST use one of these):
{registered_pages}

KNOWN APPLICATION ELEMENTS (from DOM Knowledge Base):
{dom_context}

KNOWN ACTIONS:
- navigate   — Open / go to a page (Target = page name, Value = empty)
- fill       — Enter text into a field (Target = field name, Value = the text to type)
- click      — Click a button or link (Target = element name, Value = empty)
- verify_text — Assert visible text (Target = element name, Value = empty, Expected = text to verify)
- select     — Select a dropdown option (Target = field name, Value = option text)

RAW TEST STEP:
"{raw_step}"

RULES:
1. Identify the Action from the supported list above.
2. Identify the Target — the UI element or page being acted upon.
   Use element names from the DOM context when a match is found.
3. Extract the Value — any data being entered (username, password, amount, etc.).
   If no data is entered, set value to empty string "".
4. Extract the Expected — text to verify for verify_text actions.
   If not a verification step, set expected to "".
5. The Page MUST be one of the REGISTERED PAGES listed above. Pick the closest match.
   If the step involves logging in, use the login-related page.
   If no registered page matches, use the first registered page as fallback.
6. Be precise: "Login with username Admin" → Action=fill, Target=Username, Value=Admin
7. "Press login button" → Action=click, Target=Login Button, Value=""
8. "Open parabank website" → Action=navigate, Target=Login Page, Value=""
9. "Verify accounts overview page appears" → Action=verify_text, Target=Accounts Overview Title, Value="", Expected=Accounts Overview
10. COMPOUND STEPS: If a single raw step implies MULTIPLE atomic actions, return ALL of them.
    Example: "Login using john account" (with known password demo) →
    THREE steps: fill Username + fill Password + click Login Button.
    Example: "Login as john" → fill Username john + fill Password demo + click Login Button.
    For the ParaBank demo environment, the common demo user is john with password demo.
11. Respond with ONLY valid JSON — no markdown, no explanation.
12. FORM SUBMISSION: Steps like "Apply for loan", "Submit payment", "Transfer amount",
    "Send payment" mean clicking the page's submit button.
    Use Action=click, Target=Submit Button (or "Apply Now" / "Send Payment" if visible in DOM).
    Do NOT use navigate to another page for submit/apply actions.

IMPORTANT: If the step maps to a SINGLE action, return a JSON object.
If the step maps to MULTIPLE actions, return a JSON ARRAY of objects.

Single action format:
{{"page": "...", "action": "...", "target": "...", "value": "...", "expected": ""}}

Multiple actions format (for compound steps like "Login as john"):
[{{"page": "...", "action": "fill", "target": "Username", "value": "john", "expected": ""}},
 {{"page": "...", "action": "fill", "target": "Password", "value": "demo", "expected": ""}},
 {{"page": "...", "action": "click", "target": "Login Button", "value": "", "expected": ""}}]
"""


class RawStepConverter:
    """Converts raw natural-language test steps to structured template rows."""

    def __init__(self, config: AIConfig, dom_store=None) -> None:
        self.config = config
        self.client = AzureOpenAIClient(config.azure_openai)
        self.dom_store = dom_store

    def _get_dom_context(self, raw_step: str) -> str:
        """Retrieve relevant DOM elements for grounding."""
        if self.dom_store is None:
            return "No DOM knowledge available."

        try:
            results = self.dom_store.search(raw_step, top_k=8, min_score=0.25)
            if not results:
                return "No matching DOM elements found."

            lines = []
            for r in results:
                meta = r.get("metadata", {})
                lines.append(
                    f"- Page: {meta.get('page', '?')} | "
                    f"Element: {meta.get('element_name', '?')} | "
                    f"Tag: {meta.get('tag', '')} | "
                    f"Type: {meta.get('type', '')}"
                )
            return "\n".join(lines)
        except Exception as exc:
            logger.debug("DOM context retrieval failed: %s", exc)
            return "DOM context unavailable."

    def _try_rule_based_convert(self, raw_step: str) -> list[dict[str, str]] | None:
        """Best-effort deterministic conversion for common ParaBank-style steps.

        This exists to prevent LLM mis-mappings for simple, highly-structured
        instructions like "Enter payee address city New York".

        Returns a list of rows in the LLM-output shape (keys: page/action/target/value/expected)
        or None if no rule matched.
        """
        s = (raw_step or "").strip()
        sl = s.lower()

        def _m(pattern: str) -> re.Match[str] | None:
            return re.match(pattern, s, flags=re.IGNORECASE)

        # Launch/open site
        if any(k in sl for k in ("launch", "open")) and any(k in sl for k in ("parabank", "site", "website")):
            return [{"page": "Login", "action": "navigate", "target": "Login Page", "value": "", "expected": ""}]

        # Common: open parabank portal
        if any(k in sl for k in ("launch", "open")) and "parabank" in sl and any(k in sl for k in ("portal", "app")):
            return [{"page": "Login", "action": "navigate", "target": "Login Page", "value": "", "expected": ""}]

        # Login primitives (keep atomic to avoid duplication across adjacent raw steps)
        m = _m(r"^login\s+with\s+username\s+(.+)$")
        if m:
            username = m.group(1).strip().strip('"')
            return [{"page": "Login", "action": "fill", "target": "Username", "value": username, "expected": ""}]

        m = _m(r"^(enter|type)\s+password\s+(.+)$")
        if m:
            password = m.group(2).strip().strip('"')
            return [{"page": "Login", "action": "fill", "target": "Password", "value": password, "expected": ""}]

        if any(k in sl for k in ("press", "click")) and "login" in sl and "button" in sl:
            return [{"page": "Login", "action": "click", "target": "Login Button", "value": "", "expected": ""}]

        if "verify" in sl and "accounts overview" in sl and any(k in sl for k in ("appears", "page")):
            return [
                {
                    "page": "Accounts Overview",
                    "action": "verify_text",
                    "target": "Accounts Overview Title",
                    "value": "",
                    "expected": "Accounts Overview",
                }
            ]

        # Login as john (compound)
        if sl.startswith("login") and "john" in sl:
            return [
                {"page": "Login", "action": "fill", "target": "Username", "value": "john", "expected": ""},
                {"page": "Login", "action": "fill", "target": "Password", "value": "demo", "expected": ""},
                {"page": "Login", "action": "click", "target": "Login Button", "value": "", "expected": ""},
            ]

        # Request Loan navigation
        if any(k in sl for k in ("open", "navigate", "go to")) and "request loan" in sl:
            return [{"page": "Request Loan", "action": "navigate", "target": "Request Loan", "value": "", "expected": ""}]

        m = _m(r"^enter\s+loan\s+amount\s+(.+)$")
        if m:
            value = m.group(1).strip().strip('"')
            return [{"page": "Request Loan", "action": "fill", "target": "Amount", "value": value, "expected": ""}]

        m = _m(r"^enter\s+down\s+payment\s+(.+)$")
        if m:
            value = m.group(1).strip().strip('"')
            return [{"page": "Request Loan", "action": "fill", "target": "Downpayment", "value": value, "expected": ""}]

        if "apply" in sl and "loan" in sl:
            return [{"page": "Request Loan", "action": "click", "target": "Apply Now", "value": "", "expected": ""}]

        if "verify" in sl and "loan request" in sl and "processed" in sl:
            return [
                {
                    "page": "Request Loan",
                    "action": "verify_text",
                    "target": "Loan request has been processed",
                    "value": "",
                    "expected": "Loan request has been processed",
                }
            ]

        # Navigate to Bill Pay
        if "navigate" in sl and "bill pay" in sl:
            return [{"page": "Bill Pay", "action": "navigate", "target": "Bill Pay", "value": "", "expected": ""}]

        # Bill Pay form fills (ParaBank uses these input[name] values)
        billpay_map: list[tuple[str, str]] = [
            (r"^enter\s+payee\s+name\s+(.+)$", "Payee.name"),
            (r"^enter\s+payee\s+address\s+street\s+(.+)$", "Payee.address.street"),
            (r"^enter\s+payee\s+address\s+city\s+(.+)$", "Payee.address.city"),
            (r"^enter\s+payee\s+address\s+state\s+(.+)$", "Payee.address.state"),
            (r"^enter\s+payee\s+address\s+zip\s+code\s+(.+)$", "Payee.address.zipCode"),
            (r"^enter\s+payee\s+phone\s+number\s+(.+)$", "Payee.phoneNumber"),
            (r"^enter\s+payee\s+account\s+number\s+(.+)$", "Payee.accountNumber"),
            (r"^enter\s+verify\s+account\s+number\s+(.+)$", "verifyAccount"),
            (r"^enter\s+payment\s+amount\s+(.+)$", "Amount"),
            (r"^enter\s+amount\s+(.+)$", "Amount"),
        ]
        for pat, target in billpay_map:
            m = _m(pat)
            if m:
                value = m.group(1).strip().strip('"')
                return [{"page": "Bill Pay", "action": "fill", "target": target, "value": value, "expected": ""}]

        # Submit Bill Pay
        if sl in {"send payment", "submit payment", "send the payment"} or sl.startswith("send payment"):
            return [{"page": "Bill Pay", "action": "click", "target": "Send Payment", "value": "", "expected": ""}]

        # Verify Bill Pay
        if "verify" in sl and "bill payment" in sl and "complete" in sl:
            # Keep the target as a human-visible heading so text-healing can find it.
            return [
                {
                    "page": "Bill Pay",
                    "action": "verify_text",
                    "target": "Bill Payment Complete",
                    "value": "",
                    "expected": "was successful",
                }
            ]

        return None

    def convert_step(self, raw_step: str) -> list[dict[str, str]]:
        """Convert a single raw step to one or more structured rows.

        Compound instructions (e.g. 'Login as Admin') are expanded into
        multiple atomic steps (fill username, fill password, click login).

        Returns
        -------
        list[dict[str, str]]
            One or more structured rows.
        """
        # Fast-path: deterministic conversion for known patterns
        ruled = self._try_rule_based_convert(raw_step)
        if ruled is not None:
            rows: list[dict[str, str]] = []
            for item in ruled:
                rows.append({
                    "Page": item.get("page", "Unknown"),
                    "Action": item.get("action", "unknown"),
                    "Target": item.get("target", ""),
                    "Value": item.get("value", ""),
                    "Expected": item.get("expected", ""),
                })
            return rows

        dom_context = self._get_dom_context(raw_step)

        # Build registered pages info (static + dynamic)
        page_lines = []
        for page_name in sorted(PAGE_REGISTRY.keys()):
            fields = sorted(get_supported_fields(page_name))
            page_lines.append(f"- {page_name} (fields: {', '.join(fields)})")
        for page_name in sorted(DYNAMIC_PAGES):
            page_lines.append(f"- {page_name} (dynamic — fields resolved from DOM)")
        registered_pages = "\n".join(page_lines) if page_lines else "None registered"

        prompt = _RAW_CONVERSION_PROMPT.format(
            registered_pages=registered_pages,
            dom_context=dom_context,
            raw_step=raw_step,
        )
        messages = [
            {
                "role": "system",
                "content": (
                    "You are a test automation step converter. "
                    "Respond ONLY with valid JSON (object or array)."
                ),
            },
            {"role": "user", "content": prompt},
        ]

        raw_response = self.client.chat_completion(
            messages, temperature=0.0, max_tokens=500,
        )

        # Parse JSON response
        cleaned = raw_response.strip()
        cleaned = re.sub(r"^```(?:json)?", "", cleaned)
        cleaned = re.sub(r"```$", "", cleaned)
        cleaned = cleaned.strip()

        try:
            data = json.loads(cleaned)
        except json.JSONDecodeError:
            logger.error("Failed to parse LLM response: %s", raw_response)
            return [{
                "Page": "Unknown",
                "Action": "unknown",
                "Target": raw_step,
                "Value": "",
                "Expected": "",
            }]

        # Normalise: LLM may return a single object or an array
        if isinstance(data, list):
            items = data
        else:
            items = [data]

        rows: list[dict[str, str]] = []
        for item in items:
            rows.append({
                "Page": item.get("page", "Unknown"),
                "Action": item.get("action", "unknown"),
                "Target": item.get("target", ""),
                "Value": item.get("value", ""),
                "Expected": item.get("expected", ""),
            })

        if len(rows) > 1:
            ai_logger.info(
                "[RAW→TEMPLATE] Expanded compound step into %d atomic steps",
                len(rows),
            )

        return rows

    def convert_file(
        self,
        raw_path: str | Path,
        output_path: str | Path,
    ) -> str:
        """Convert a raw Excel file to structured template format.

        Parameters
        ----------
        raw_path : str | Path
            Path to the raw Excel file (TC_ID, Step_Order, Raw_Step).
        output_path : str | Path
            Path to write the structured Excel output.

        Returns
        -------
        str
            The output file path.
        """
        raw_path = Path(raw_path)
        output_path = Path(output_path)

        if not raw_path.exists():
            raise FileNotFoundError(f"Raw Excel file not found: {raw_path}")

        df = pd.read_excel(raw_path, dtype=str).fillna("")

        # Validate expected columns
        required = {"TC_ID", "Step_Order", "Raw_Step"}
        missing = required - set(df.columns)
        if missing:
            raise ValueError(
                f"Raw Excel missing required columns: {missing}. "
                f"Expected: TC_ID, Step_Order, Raw_Step"
            )

        total_steps = len(df)
        logger.info(
            "Converting %d raw steps from %s", total_steps, raw_path.name,
        )

        structured_rows: list[dict[str, str]] = []

        # Track per-test-case navigation context to avoid LLM "Page" drift.
        known_pages = set(PAGE_REGISTRY.keys()) | set(DYNAMIC_PAGES)
        current_page_by_tc: dict[str, str] = {}

        for idx, row in df.iterrows():
            tc_id = row["TC_ID"]
            raw_step = row["Raw_Step"]
            step_num = int(idx) + 1

            ai_logger.info("")
            ai_logger.info("─" * 50)
            ai_logger.info(
                "[RAW→TEMPLATE] Step %d/%d: \"%s\" (TC: %s)",
                step_num, total_steps, raw_step, tc_id,
            )

            converted_rows = self.convert_step(raw_step)

            # Stabilize Page selection based on last navigate for this TC.
            for sub in converted_rows:
                action = (sub.get("Action") or "").strip().lower()
                page = (sub.get("Page") or "").strip()

                if action == "navigate":
                    target = (sub.get("Target") or "").strip()
                    if target:
                        current_page_by_tc[tc_id] = target
                    continue

                current = current_page_by_tc.get(tc_id, "")
                if current and action in {"fill", "click", "verify_text", "select"}:
                    # If the LLM picked an unrelated registered page, prefer the last navigated page.
                    # (This matches how humans execute flows and how the generated steps use _current_page.)
                    if page not in known_pages or page != current:
                        sub["Page"] = current

            for sub in converted_rows:
                sub["TC_ID"] = tc_id
                ai_logger.info(
                    "[RAW→TEMPLATE] → Page=%s  Action=%s  Target=%s  Value=%s  Expected=%s",
                    sub["Page"],
                    sub["Action"],
                    sub["Target"],
                    sub.get("Value", ""),
                    sub.get("Expected", ""),
                )

            ai_logger.info("─" * 50)

            structured_rows.extend(converted_rows)

        # Build output DataFrame in the correct column order
        out_df = pd.DataFrame(
            structured_rows,
            columns=["TC_ID", "Page", "Action", "Target", "Value", "Expected"],
        )

        # Write to Excel
        out_df.to_excel(str(output_path), index=False, engine="openpyxl")
        logger.info(
            "Structured template written: %s (%d rows)",
            output_path.name, len(out_df),
        )

        return str(output_path)
