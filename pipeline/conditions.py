"""
Structured condition evaluator for config-driven pipelines.

Phase 3.5 — replaces the simple string-based condition evaluator with a
composable operator tree that supports:

  - Comparison operators: eq, neq, gt, gte, lt, lte
  - Existence/truthiness: exists, truthy, falsy
  - Logical combinators: and, or, not
  - Backward compatibility with Phase 3 string conditions

Condition objects are plain dicts (JSON-serializable), e.g.::

    {"eq": ["$steps.validate.data.row_count", 10]}
    {"and": [
        {"truthy": "$input.force"},
        {"neq": ["$steps.detect_excel.data.excel_path", null]}
    ]}

String conditions from Phase 3 are auto-detected and delegated to the
legacy evaluator for full backward compatibility.
"""
from __future__ import annotations

import logging
import re
from typing import Any

logger = logging.getLogger("pipeline.conditions")


# ---------------------------------------------------------------------------
# Reference resolution (shared with service.py context model)
# ---------------------------------------------------------------------------

def resolve_ref(
    ref: str,
    results_map: dict[str, Any],
    input_ns: dict[str, Any],
) -> Any:
    """Resolve a ``$``-prefixed reference against the pipeline context.

    Supported reference formats:
      - ``$steps.step_name.data.key``  (Phase 3.5 formal)
      - ``$step_name.data.key``        (Phase 3 legacy)
      - ``$input.field``               (runtime input)
      - ``$steps.step_name.ok``        (bool success)
      - ``$steps.step_name.error``     (error message)

    Literal values (non-string or strings not starting with ``$``) are
    returned as-is.
    """
    if not isinstance(ref, str) or not ref.startswith("$"):
        return ref

    path = ref[1:]  # strip leading $
    parts = path.split(".")

    # --- $input.field ---
    if parts[0] == "input":
        key = parts[1] if len(parts) > 1 else ""
        return input_ns.get(key)

    # --- $steps.step_name.data.key (Phase 3.5 formal) ---
    if parts[0] == "steps" and len(parts) >= 2:
        step_name = parts[1]
        remainder = parts[2:]  # e.g. ["data", "key"] or ["ok"]
        return _resolve_step_attr(step_name, remainder, results_map)

    # --- $step_name.data.key (Phase 3 legacy) ---
    step_name = parts[0]
    remainder = parts[1:]
    return _resolve_step_attr(step_name, remainder, results_map)


def _resolve_step_attr(
    step_name: str,
    attr_parts: list[str],
    results_map: dict[str, Any],
) -> Any:
    """Drill into a StepResult by attribute path."""
    if step_name not in results_map:
        return None

    sr = results_map[step_name]

    if not attr_parts:
        return sr

    prop = attr_parts[0]

    if prop == "ok":
        return sr.ok
    elif prop == "error":
        return sr.error
    elif prop == "duration_ms":
        return sr.duration_ms
    elif prop == "data":
        if len(attr_parts) == 1:
            return sr.data
        # Support nested data access: data.key or data.key.subkey
        obj = sr.data
        for key in attr_parts[1:]:
            if isinstance(obj, dict):
                obj = obj.get(key)
            else:
                return None
        return obj
    else:
        return None


# ---------------------------------------------------------------------------
# Condition evaluator
# ---------------------------------------------------------------------------

class ConditionEvaluator:
    """Evaluate structured or string-based conditions against pipeline context.

    Usage::

        evaluator = ConditionEvaluator(results_map, input_ns)

        # Structured condition (Phase 3.5)
        evaluator.evaluate({"eq": ["$steps.validate.ok", True]})

        # String condition (Phase 3 backward compat)
        evaluator.evaluate("$validate.ok == true")

        # Always-true / always-false
        evaluator.evaluate("true")
        evaluator.evaluate(None)  # None => True (no condition)
    """

    def __init__(
        self,
        results_map: dict[str, Any],
        input_ns: dict[str, Any],
    ) -> None:
        self._results_map = results_map
        self._input_ns = input_ns

    def evaluate(self, condition: Any) -> bool:
        """Evaluate a condition expression.

        Parameters
        ----------
        condition : dict | str | None
            - ``None`` => True (unconditional)
            - ``str``  => legacy string evaluation (Phase 3 compat)
            - ``dict`` => structured operator evaluation (Phase 3.5)
            - ``bool`` => returned directly

        Returns
        -------
        bool
            Whether the condition is satisfied.
        """
        if condition is None:
            return True

        if isinstance(condition, bool):
            return condition

        if isinstance(condition, str):
            return self._evaluate_string(condition)

        if isinstance(condition, dict):
            return self._evaluate_structured(condition)

        logger.warning("Unsupported condition type %s — defaulting to True", type(condition).__name__)
        return True

    # ------------------------------------------------------------------
    # Structured evaluation (Phase 3.5)
    # ------------------------------------------------------------------

    def _evaluate_structured(self, cond: dict[str, Any]) -> bool:
        """Evaluate an operator-based condition dict.

        Supported operators:
          Comparison: eq, neq, gt, gte, lt, lte
          Existence:  exists, truthy, falsy
          Logical:    and, or, not
        """
        if not cond:
            return True  # empty dict => unconditional

        # Exactly one key expected (the operator)
        if len(cond) != 1:
            logger.warning("Condition dict must have exactly one operator key, got %s", list(cond.keys()))
            return True

        op = next(iter(cond))
        operand = cond[op]

        # --- Logical operators ---
        if op == "and":
            if not isinstance(operand, list):
                logger.warning("'and' operator requires a list of sub-conditions")
                return True
            return all(self._evaluate_structured(sub) if isinstance(sub, dict)
                      else self.evaluate(sub) for sub in operand)

        if op == "or":
            if not isinstance(operand, list):
                logger.warning("'or' operator requires a list of sub-conditions")
                return True
            return any(self._evaluate_structured(sub) if isinstance(sub, dict)
                      else self.evaluate(sub) for sub in operand)

        if op == "not":
            if isinstance(operand, dict):
                return not self._evaluate_structured(operand)
            return not self.evaluate(operand)

        # --- Existence / truthiness (unary) ---
        if op == "exists":
            ref_val = self._resolve(operand)
            return ref_val is not None

        if op == "truthy":
            ref_val = self._resolve(operand)
            return bool(ref_val)

        if op == "falsy":
            ref_val = self._resolve(operand)
            return not bool(ref_val)

        # --- Comparison operators (binary: [left, right]) ---
        if op in ("eq", "neq", "gt", "gte", "lt", "lte"):
            if not isinstance(operand, list) or len(operand) != 2:
                logger.warning("'%s' operator requires a list of [left, right]", op)
                return True
            left = self._resolve(operand[0])
            right = self._resolve(operand[1])
            return self._compare(op, left, right)

        logger.warning("Unknown condition operator: %s", op)
        return True

    def _compare(self, op: str, left: Any, right: Any) -> bool:
        """Perform a typed comparison."""
        try:
            if op == "eq":
                return left == right
            elif op == "neq":
                return left != right
            elif op == "gt":
                return left > right
            elif op == "gte":
                return left >= right
            elif op == "lt":
                return left < right
            elif op == "lte":
                return left <= right
        except TypeError:
            # Incomparable types (e.g. None > 5)
            logger.debug("Type error comparing %r %s %r", left, op, right)
            return False
        return False

    def _resolve(self, value: Any) -> Any:
        """Resolve a value — if it's a $reference, resolve it; otherwise literal."""
        return resolve_ref(value, self._results_map, self._input_ns)

    # ------------------------------------------------------------------
    # String evaluation (Phase 3 backward compat)
    # ------------------------------------------------------------------

    def _evaluate_string(self, condition: str) -> bool:
        """Evaluate a plain-string condition (Phase 3 format).

        Supported expressions:
          - ``"true"`` / ``"false"``
          - ``"$step.ok"`` / ``"$step.ok == true"``
          - ``"$step.data.key == value"``
          - ``"$step.data.key != value"``
          - ``"$input.field == value"``
        """
        cond = condition.strip()

        if cond.lower() in ("true", "1", "yes"):
            return True
        if cond.lower() in ("false", "0", "no"):
            return False

        # Parse comparison: <ref> <op> <value>
        match = re.match(r'^(\$[\w.]+)\s*(==|!=|>=|<=|>|<)\s*(.+)$', cond)
        if match:
            ref_str, op, raw_val = match.group(1), match.group(2), match.group(3).strip()
            resolved = resolve_ref(ref_str, self._results_map, self._input_ns)

            # Parse the comparison value
            compare_val = self._parse_literal(raw_val)

            op_map = {"==": "eq", "!=": "neq", ">": "gt", ">=": "gte", "<": "lt", "<=": "lte"}
            return self._compare(op_map.get(op, "eq"), resolved, compare_val)

        # Bare reference: truthy check
        if cond.startswith("$"):
            resolved = resolve_ref(cond, self._results_map, self._input_ns)
            return bool(resolved)

        return True  # Unknown conditions default to true (safe fallback)

    @staticmethod
    def _parse_literal(raw: str) -> Any:
        """Parse a string literal into a typed Python value."""
        if raw.lower() == "true":
            return True
        if raw.lower() == "false":
            return False
        if raw.lower() in ("none", "null"):
            return None
        try:
            return int(raw)
        except ValueError:
            pass
        try:
            return float(raw)
        except ValueError:
            pass
        return raw.strip("'\"")


# ---------------------------------------------------------------------------
# Module-level convenience function
# ---------------------------------------------------------------------------

def evaluate_condition(
    condition: Any,
    results_map: dict[str, Any],
    input_ns: dict[str, Any],
) -> bool:
    """Convenience wrapper — evaluate a condition without instantiating the class."""
    return ConditionEvaluator(results_map, input_ns).evaluate(condition)
