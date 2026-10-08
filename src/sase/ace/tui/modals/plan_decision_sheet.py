"""Draft values, edits, reset, sheet, and summaries for Plan Decisions.

Pure Python, no Textual imports, so unit tests do not need a pilot.
Wraps ``sase.sdd.plan_decisions.sheet_binding`` / ``summary_binding``
when the Rust core is available, with a Python fallback that matches
the wire shape (rows in author order plus counts).
"""

from __future__ import annotations

from typing import Any


def _effective_default(definition: dict[str, Any]) -> Any:
    if "effective_default" in definition:
        return definition["effective_default"]
    return definition.get("default")


def _initial_values(definitions: list[dict[str, Any]]) -> dict[str, Any]:
    values: dict[str, Any] = {}
    for definition in definitions:
        decision_id = str(definition.get("id", ""))
        if not decision_id:
            continue
        values[decision_id] = _effective_default(definition)
    return values


def _choice_keys(definition: dict[str, Any]) -> list[str]:
    keys: list[str] = []
    for choice in definition.get("choices", []) or []:
        if isinstance(choice, dict) and "key" in choice:
            keys.append(str(choice["key"]))
    return keys


def _fallback_sheet(
    definitions: list[dict[str, Any]],
    values: dict[str, Any],
    review_revision: int,
) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    for definition in definitions:
        decision_id = str(definition.get("id", ""))
        if not decision_id:
            continue
        kind = str(definition.get("kind", ""))
        value = values.get(decision_id, _effective_default(definition))
        # Canonicalize choice casing to authored spelling.
        if kind == "choice" and isinstance(value, str):
            for key in _choice_keys(definition):
                if key.lower() == value.lower():
                    value = key
                    break
        default = _effective_default(definition)
        memory_def = definition.get("memory")
        memory: dict[str, Any] | None = None
        if isinstance(memory_def, dict) or memory_def is not None:
            if isinstance(definition.get("memory"), dict):
                memory_def = definition["memory"]
            else:
                memory_def = {}
            selectors = (
                list(memory_def.get("selectors", []))
                if isinstance(memory_def, dict)
                else []
            )
            memory = {
                "selectors": [str(s) for s in selectors],
                "resolved": list(definition.get("resolved", []) or []),
                "provenance": str(
                    definition.get("provenance", "not_asked") or "not_asked"
                ),
                "quote": definition.get("requested")
                if isinstance(definition.get("requested"), str)
                else definition.get("quote"),
            }
            # Frozen definitions carry memory + provenance at top level;
            # sheet memory nests selectors/provenance/quote.
            if isinstance(definition.get("memory"), dict):
                nested = definition["memory"]
                if isinstance(nested, dict):
                    if "selectors" in nested:
                        memory["selectors"] = [
                            str(s) for s in (nested.get("selectors") or [])
                        ]
                    if "provenance" in nested:
                        memory["provenance"] = str(nested.get("provenance"))
                    if "quote" in nested:
                        memory["quote"] = nested.get("quote")
                    if "resolved" in nested:
                        memory["resolved"] = nested.get("resolved")
        rows.append(
            {
                "id": decision_id,
                "kind": "toggle" if kind == "toggle" else "choice",
                "ask": str(definition.get("ask", "")),
                **(
                    {"why": definition["why"]}
                    if isinstance(definition.get("why"), str)
                    else {}
                ),
                "choices": list(definition.get("choices", []) or []),
                "default": default,
                "value": value,
                "changed": bool(value != default),
                **({"memory": memory} if memory is not None else {}),
            }
        )
    memory_count = sum(1 for row in rows if "memory" in row)
    changed_count = sum(1 for row in rows if row.get("changed"))
    return {
        "count": len(rows),
        "memory_count": memory_count,
        "changed_count": changed_count,
        "review_revision": int(review_revision),
        "rows": rows,
    }


def _fallback_short_summary(sheet: dict[str, Any]) -> str:
    rows = sheet.get("rows") if isinstance(sheet, dict) else []
    if not isinstance(rows, list):
        rows = []
    changed = sum(1 for row in rows if isinstance(row, dict) and row.get("changed"))
    if changed == 0:
        base = "defaults"
    elif changed == 1:
        base = "1 change"
    else:
        base = f"{changed} changes"
    memory_on = any(
        isinstance(row, dict)
        and isinstance(row.get("memory"), dict)
        and row.get("value") is True
        for row in rows
    )
    return f"{base} · 🧠" if memory_on else base


def _fallback_full_summary(sheet: dict[str, Any], verdict: str) -> str:
    from sase.sdd._plan_display_decisions import format_decision_value

    rows = sheet.get("rows") if isinstance(sheet, dict) else []
    if not isinstance(rows, list):
        rows = []
    parts = [f"→ {verdict}"]
    for row in rows:
        if not isinstance(row, dict) or "memory" in row:
            continue
        mark = " ●" if row.get("changed") else ""
        parts.append(f"{row.get('id')}={format_decision_value(row.get('value'))}{mark}")
    selectors: list[str] = []
    has_memory = False
    for row in rows:
        if not isinstance(row, dict) or not isinstance(row.get("memory"), dict):
            continue
        has_memory = True
        if row.get("value") is not True:
            continue
        memory = row["memory"]
        for selector in memory.get("selectors", []) or []:
            text = str(selector)
            if text and text not in selectors:
                selectors.append(text)
    if has_memory:
        if not selectors:
            parts.append("🧠 no memory edits")
        else:
            parts.append(f"🧠 {', '.join(selectors)}")
    return " · ".join(parts)


class PlanDecisionDraft:
    """Mutable draft values for one plan review."""

    def __init__(
        self,
        definitions: list[dict[str, Any]],
        values: dict[str, Any] | None = None,
        review_revision: int = 0,
    ) -> None:
        self._definitions = list(definitions or [])
        self._by_id = {
            str(d.get("id", "")): d
            for d in self._definitions
            if str(d.get("id", "")).strip()
        }
        initial = _initial_values(self._definitions)
        if values:
            for key, value in values.items():
                if str(key) in self._by_id:
                    initial[str(key)] = value
        self._values = initial
        self._review_revision = int(review_revision)

    @property
    def definitions(self) -> list[dict[str, Any]]:
        return list(self._definitions)

    @property
    def review_revision(self) -> int:
        return self._review_revision

    @property
    def ids(self) -> list[str]:
        return [str(d.get("id", "")) for d in self._definitions if str(d.get("id", ""))]

    def value_for(self, decision_id: str) -> Any:
        return self._values.get(str(decision_id))

    def values(self) -> dict[str, Any]:
        return dict(self._values)

    def set_value(self, decision_id: str, value: Any) -> None:
        key = str(decision_id)
        if key not in self._by_id:
            return
        definition = self._by_id[key]
        kind = str(definition.get("kind", ""))
        if kind == "toggle":
            self._values[key] = bool(value)
        else:
            keys = _choice_keys(definition)
            text = str(value)
            for choice_key in keys:
                if choice_key.lower() == text.lower():
                    self._values[key] = choice_key
                    return
            if keys:
                self._values[key] = value

    def step(self, decision_id: str, delta: int) -> None:
        key = str(decision_id)
        definition = self._by_id.get(key)
        if definition is None:
            return
        kind = str(definition.get("kind", ""))
        if kind == "toggle":
            self._values[key] = True if delta > 0 else False
            return
        keys = _choice_keys(definition)
        if not keys:
            return
        current = self._values.get(key)
        try:
            index = keys.index(str(current))
        except ValueError:
            # Case-insensitive fallback to authored spelling.
            lowered = str(current).lower()
            index = next((i for i, k in enumerate(keys) if k.lower() == lowered), 0)
        self._values[key] = keys[(index + delta) % len(keys)]

    def flip(self, decision_id: str) -> None:
        key = str(decision_id)
        definition = self._by_id.get(key)
        if definition is None:
            return
        if str(definition.get("kind", "")) == "toggle":
            self._values[key] = not bool(self._values.get(key))
        else:
            self.step(key, 1)

    def reset(self, decision_id: str) -> None:
        key = str(decision_id)
        definition = self._by_id.get(key)
        if definition is None:
            return
        self._values[key] = _effective_default(definition)

    def reset_all(self) -> None:
        self._values = _initial_values(self._definitions)

    def decision_map(self) -> dict[str, Any]:
        return {f"decision_{key}": value for key, value in self._values.items()}

    def sheet(self) -> dict[str, Any]:
        try:
            from sase.sdd.plan_decisions import sheet_binding

            return sheet_binding(
                self._definitions, dict(self._values), self._review_revision
            )
        except Exception:
            return _fallback_sheet(
                self._definitions, dict(self._values), self._review_revision
            )

    def full_summary(self, verdict: str) -> str:
        sheet = self.sheet()
        try:
            from sase.sdd.plan_decisions import summary_binding

            return summary_binding(sheet, verdict, "full")
        except Exception:
            return _fallback_full_summary(sheet, verdict)

    def short_summary(self, verdict: str) -> str:
        sheet = self.sheet()
        try:
            from sase.sdd.plan_decisions import summary_binding

            return summary_binding(sheet, verdict, "short")
        except Exception:
            return _fallback_short_summary(sheet)

    def feedback_carry_lines(self) -> list[str]:
        from sase.sdd._plan_display_decisions import format_decision_value

        sheet = self.sheet()
        rows = sheet.get("rows") if isinstance(sheet, dict) else []
        lines: list[str] = []
        if not isinstance(rows, list):
            return lines
        for row in rows:
            if not isinstance(row, dict) or not row.get("changed"):
                continue
            lines.append(
                f"Carries: {row.get('id')} → {format_decision_value(row.get('value'))}"
            )
        return lines


def verdict_for_selection(*, commit_plan: bool, run_coder: bool, epic: bool) -> str:
    if epic:
        return "epic launch"
    if commit_plan and run_coder:
        return "coder + commit"
    if run_coder:
        return "coder"
    return "commit"


__all__ = [
    "PlanDecisionDraft",
    "verdict_for_selection",
]
