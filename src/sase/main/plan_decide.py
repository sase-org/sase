"""Parsing, validation, and card rendering for ``sase plan approve -D``.

One home for the ``ID=VALUE`` handling every approval route shares: the
repeatable ``-D/--decide`` parse (duplicate ids are an error), toggle
spellings shared with :mod:`sase.macro.models`, case-insensitive choice
keys with no prefix matching, did-you-mean errors that name the allowed
values with ``★`` on the default, the agent-boundary memory refusal, and
the shared decision card from the epic plan's Section 1.4.
"""

from __future__ import annotations

from difflib import get_close_matches
from typing import Any

from sase._plan_approval_protocol import PlanApprovalActionError

#: Toggle spellings shared with ``macro/models.py`` ``InputType.BOOL``.
BOOL_TRUE_WORDS = ("true", "1", "yes", "on")
BOOL_FALSE_WORDS = ("false", "0", "no", "off")

_SUGGESTION_CUTOFF = 0.5


class DecideError(PlanApprovalActionError):
    """A ``-D`` failure rendered as a multi-line card, already formatted."""

    def __init__(
        self,
        header: str,
        detail_lines: tuple[str, ...] = (),
        hints: tuple[str, ...] = (),
    ) -> None:
        super().__init__("decide_invalid", "decide", header)
        self.header = header
        self.detail_lines = detail_lines
        self.hints = hints


def parse_decide_assignments(raw_items: list[str] | tuple[str, ...]) -> dict[str, str]:
    """Split raw ``-D ID=VALUE`` strings into ``{id: raw value}``.

    Raises :class:`DecideError` when an entry has no ``=``, an empty id,
    or repeats an id.
    """
    parsed: dict[str, str] = {}
    for raw in raw_items:
        item = raw.strip()
        name, sep, value = item.partition("=")
        name = name.strip()
        value = value.strip()
        if not sep or not name:
            raise DecideError(
                f"✗ bad -D value {raw!r}. Use ID=VALUE, for example -D grouping=mode.",
                ("  decisions take ID=VALUE, one -D per decision",),
            )
        if name in parsed:
            raise DecideError(
                f"✗ duplicate -D {name!r}. Giving the same id twice is an error.",
                (f"  pass -D {name}=<value> once",),
            )
        parsed[name] = value
    return parsed


def caller_for_decide() -> str:
    """Return the resolver caller for this shell: ``agent`` or ``human``.

    Delegates to the same fail-closed classifier as
    ``notification_gates.executor.gate_response_caller``: any unknown actor
    or classifier exception becomes ``agent``, never ``human``.
    """
    try:
        from sase.notification_gates.executor import gate_response_caller
    except Exception:
        return "agent"
    try:
        caller = gate_response_caller()
    except Exception:
        return "agent"
    return caller if caller in ("human", "agent") else "agent"


def _agent_display_name() -> str:
    """Return the running agent's name for the boundary message, if any."""
    try:
        from sase.bead.attribution import acting_agent_name
    except Exception:
        return "unknown agent"
    try:
        return acting_agent_name() or "unknown agent"
    except Exception:
        return "unknown agent"


def _definition_by_id(
    definitions: list[dict[str, Any]], decision_id: str
) -> dict[str, Any] | None:
    for definition in definitions:
        if str(definition.get("id", "")) == decision_id:
            return definition
    return None


def _allowed_line(definition: dict[str, Any]) -> str:
    """Render one decision's allowed values with ``★`` on the default."""
    decision_id = str(definition.get("id", ""))
    default = definition.get("default")
    kind = str(definition.get("kind", ""))
    if kind == "choice":
        parts = []
        for choice in definition.get("choices", []) or []:
            if not isinstance(choice, dict):
                continue
            key = str(choice.get("key", ""))
            star = " ★" if key == default else ""
            parts.append(f"{key}{star}")
        return f"  {decision_id}: {', '.join(parts)}"
    default_word = "yes" if default is True else "no"
    other = "no" if default is True else "yes"
    if default is True:
        return f"  {decision_id}: {default_word} ★, {other}"
    return f"  {decision_id}: {default_word} ★, {other}"


def _memory_is_new(memory: dict[str, Any]) -> bool:
    """Return True when a memory row grants a note that does not exist yet."""
    resolved = memory.get("resolved")
    if not isinstance(resolved, list):
        return False
    return any(
        isinstance(record, dict) and record.get("exists") is False
        for record in resolved
    )


def _did_you_mean(unknown: str, ids: list[str]) -> str:
    matches = get_close_matches(unknown, ids, n=1, cutoff=_SUGGESTION_CUTOFF)
    if matches:
        return f" Did you mean {matches[0]!r}?"
    return ""


def _build_decide_submitted(
    definitions: list[dict[str, Any]],
    raw_map: dict[str, str],
    *,
    caller: str,
) -> dict[str, Any]:
    """Validate raw ``-D`` values against frozen definitions.

    Returns ``{id: typed value}`` for the core resolver. Toggle values use
    the shared bool spellings; choice keys match case-insensitively with no
    prefix matching. An agent switching a memory decision on is refused
    with the boundary message unless its effective default is already true.
    """
    ids = [str(item.get("id", "")) for item in definitions]
    submitted: dict[str, Any] = {}
    for decision_id, raw_value in raw_map.items():
        definition = _definition_by_id(definitions, decision_id)
        if definition is None:
            lines = tuple(_allowed_line(item) for item in definitions)
            raise DecideError(
                f"✗ unknown decision {decision_id!r}.{_did_you_mean(decision_id, ids)}",
                lines,
            )
        kind = str(definition.get("kind", ""))
        if kind == "choice":
            keys = [
                str(choice.get("key", ""))
                for choice in definition.get("choices", []) or []
                if isinstance(choice, dict)
            ]
            lowered = raw_value.lower()
            match = next((key for key in keys if key.lower() == lowered), None)
            if match is None:
                raise DecideError(
                    f"✗ bad value {raw_value!r} for decision {decision_id!r}."
                    f"{_did_you_mean(raw_value, keys)}",
                    (_allowed_line(definition),),
                )
            submitted[decision_id] = match
        else:
            lowered = raw_value.lower()
            if lowered in BOOL_TRUE_WORDS:
                submitted[decision_id] = True
            elif lowered in BOOL_FALSE_WORDS:
                submitted[decision_id] = False
            else:
                raise DecideError(
                    f"✗ bad value {raw_value!r} for decision {decision_id!r}.",
                    (_allowed_line(definition),),
                )
    if caller == "agent":
        for decision_id, value in submitted.items():
            if value is not True:
                continue
            definition = _definition_by_id(definitions, decision_id)
            if definition is None or definition.get("memory") is None:
                continue
            if definition.get("effective_default") is True:
                continue
            raise DecideError(
                "✗ memory decisions can only be switched on by a human; "
                f"this shell runs inside agent {_agent_display_name()}.",
            )
    return submitted


def resolve_decide_values(
    definitions: list[dict[str, Any]],
    raw_map: dict[str, str],
    *,
    caller: str,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Validate ``-D`` input and resolve the full accepted vector.

    Returns ``(values, rows)`` from the core resolver, where each row
    carries ``id``, ``value``, ``source`` (``default``/``submitted``/
    ``clamped``), and ``changed``.
    """
    from sase.sdd.plan_decisions import resolve_binding

    submitted = _build_decide_submitted(definitions, raw_map, caller=caller)
    try:
        resolved = resolve_binding(definitions, submitted, caller)
    except Exception as exc:
        raise DecideError(
            f"✗ plan decisions failed to resolve: {exc}",
        ) from exc
    errors = resolved.get("errors") or []
    if errors:
        first = errors[0] if isinstance(errors[0], dict) else {}
        code = str(first.get("code") or "decision-resolve-failed")
        message = str(first.get("message") or "plan decisions failed to resolve")
        if code == "memory_decision_requires_human":
            raise DecideError(
                "✗ memory decisions can only be switched on by a human; "
                f"this shell runs inside agent {_agent_display_name()}.",
            )
        raise DecideError(f"✗ {message}")
    values = resolved.get("values")
    rows = resolved.get("rows")
    if not isinstance(values, dict):
        raise DecideError("✗ plan decisions failed to resolve: no values")
    if not isinstance(rows, list):
        rows = []
    return dict(values), [row for row in rows if isinstance(row, dict)]


def verdict_for_kind(kind: str | None) -> str:
    """Map an approval kind to the summary sentence's verdict words."""
    if kind == "epic":
        return "epic launch"
    if kind == "commit":
        return "commit"
    if kind == "approve":
        return "coder"
    return "coder + commit"


def already_approved_decide_error(raw_map: dict[str, str]) -> DecideError:
    """Refuse ``-D`` on an already-approved plan: retry reuses answers."""
    ids = ", ".join(raw_map)
    return DecideError(
        "This plan is already approved. Retry uses its accepted answers. "
        f"Start a new review to change {ids}.",
    )


def resolve_direct_decisions(
    validation: Any,
    raw_map: dict[str, str],
    *,
    caller: str,
) -> (
    tuple[dict[str, Any], list[dict[str, Any]], dict[str, Any], list[dict[str, Any]]]
    | None
):
    """Resolve ``-D`` answers for a gateless approval file.

    Thin parser/card adapter over the single shared direct resolver:
    duplicate ids, boolean spellings, case-insensitive choice keys, and
    allowed-value hints stay here; host facts are built once and typed
    overrides go to the shared resolver. Returns
    ``(values, rows, sheet, definitions)`` when the plan declares decisions
    and ``None`` when it declares none (raising when ``-D`` was passed
    anyway).
    """
    from sase.sdd.plan_decisions import (
        artifacts_dir_from_env,
        build_definitions,
        resolve_plan_decisions_for_direct_approval,
        sheet_binding,
    )

    plan = getattr(validation, "plan", None)
    decisions = getattr(plan, "decisions", ()) if plan is not None else ()
    if not decisions:
        if raw_map:
            raise DecideError(
                "✗ this plan has no decisions; "
                f"-D {next(iter(raw_map))} matches nothing.",
            )
        return None
    try:
        definitions = build_definitions(validation, artifacts_dir_from_env())
    except Exception as exc:
        raise DecideError(
            f"✗ plan decisions failed to resolve: {exc}",
        ) from exc
    try:
        submitted = _build_decide_submitted(definitions, raw_map, caller=caller)
    except DecideError:
        raise
    except Exception as exc:
        raise DecideError(
            f"✗ plan decisions failed to resolve: {exc}",
        ) from exc
    try:
        resolved = resolve_plan_decisions_for_direct_approval(
            validation, submitted, caller, definitions=list(definitions)
        )
    except Exception as exc:
        raise DecideError(
            f"✗ plan decisions failed to resolve: {exc}",
        ) from exc
    errors = resolved.get("errors") or []
    if errors:
        first = errors[0] if isinstance(errors[0], dict) else {}
        code = str(first.get("code") or "decision-resolve-failed")
        message = str(first.get("message") or "plan decisions failed to resolve")
        if code == "memory_decision_requires_human":
            raise DecideError(
                "✗ memory decisions can only be switched on by a human; "
                f"this shell runs inside agent {_agent_display_name()}.",
            )
        raise DecideError(f"✗ {message}")
    values = resolved.get("values")
    rows = resolved.get("rows")
    frozen = resolved.get("definitions")
    if not isinstance(values, dict):
        raise DecideError("✗ plan decisions failed to resolve: no values")
    if not isinstance(rows, list):
        rows = []
    typed_rows = [row for row in rows if isinstance(row, dict)]
    frozen_definitions = (
        [dict(item) for item in frozen]
        if isinstance(frozen, list) and frozen
        else [dict(item) for item in definitions]
    )
    try:
        sheet = sheet_binding(frozen_definitions, dict(values), 0)
    except Exception as exc:
        raise DecideError(
            f"✗ plan decisions failed to resolve: {exc}",
        ) from exc
    return dict(values), typed_rows, sheet, frozen_definitions


def direct_card_lines(plan: Any, *, dry_run: bool) -> list[str] | None:
    """Render the Section 1.4 card for a resolved direct approval."""
    sheet = getattr(plan, "decide_sheet", None)
    if not isinstance(sheet, dict) or not sheet:
        return None
    rows = getattr(plan, "decide_rows", ())
    rows = [row for row in rows if isinstance(row, dict)]
    return decision_card_lines(
        kind_label=str(getattr(plan, "kind", "tale") or "tale"),
        plan_name=str(getattr(plan, "name", "") or ""),
        review_revision=0,
        sheet=sheet,
        rows=rows,
        verdict=verdict_for_kind(str(getattr(plan, "kind", None))),
        dry_run=dry_run,
    )


def retry_line_for_plan(path: object) -> str | None:
    """Render the retry line from a stamped plan's accepted answers."""
    try:
        from sase.sdd.plan_decision_handoff import load_stamped_decisions
    except Exception:
        return None
    try:
        stamped = load_stamped_decisions(path)  # type: ignore[arg-type]
    except Exception:
        return None
    if stamped is None or getattr(stamped, "decided_by", None) is None:
        return None
    if not getattr(stamped, "values", None):
        return None
    return (
        "Retrying implementation with the accepted decisions: "
        f"{_format_values_sentence(dict(stamped.values))}."
    )


def _format_values_sentence(values: dict[str, Any]) -> str:
    """Render ``grouping=mode; tui_note=no`` for retry messages."""
    from sase.sdd._plan_display_decisions import format_decision_value

    return "; ".join(
        f"{key}={format_decision_value(value)}" for key, value in values.items()
    )


def decision_card_lines(
    *,
    kind_label: str,
    plan_name: str,
    review_revision: int,
    sheet: dict[str, Any],
    rows: list[dict[str, Any]],
    verdict: str,
    dry_run: bool,
) -> list[str]:
    """Build the Section 1.4 decision card as plain lines.

    Row sources read ``-D`` for submitted values and ``default`` otherwise
    (a ``clamped`` source is a default with a quote warning, never ``-D``);
    changed rows carry ``●`` and name the prior default with ``was ★``,
    unchanged rows carry ``★``, and memory rows carry provenance chips
    without duplication plus the ``new`` chip for missing notes.
    The closing line is the core summary sentence.
    """
    from sase.sdd._plan_display_decisions import format_decision_value
    from sase.sdd.plan_decisions import summary_binding

    lines: list[str] = []
    if dry_run:
        head = f"◇ Dry run · {kind_label} · {plan_name}"
        if review_revision > 0:
            head += f" · review {review_revision}"
        lines.append(head)
    by_id = {str(row.get("id", "")): row for row in rows if isinstance(row, dict)}
    sheet_rows = sheet.get("rows")
    ordered = (
        [row for row in sheet_rows if isinstance(row, dict)]
        if isinstance(sheet_rows, list)
        else []
    )
    width = max((len(str(row.get("id", ""))) for row in ordered), default=0)
    for sheet_row in ordered:
        decision_id = str(sheet_row.get("id", ""))
        row = by_id.get(decision_id, {})
        value = row.get("value", sheet_row.get("value", sheet_row.get("default")))
        changed = bool(row.get("changed", sheet_row.get("changed", False)))
        source = str(row.get("source", "default"))
        origin = "-D" if source == "submitted" else "default"
        display = format_decision_value(value)
        mark = " ●" if changed else " ★"
        line = f"  {decision_id.ljust(width)}   {display}{mark}   {origin}"
        if changed:
            default = sheet_row.get("default", row.get("default"))
            line += f"        was ★ {format_decision_value(default)}"
        memory = sheet_row.get("memory")
        if isinstance(memory, dict):
            selectors = memory.get("selectors")
            names = (
                ", ".join(str(item) for item in selectors if str(item).strip())
                if isinstance(selectors, list)
                else ""
            )
            provenance = str(memory.get("provenance") or "").strip()
            chip = {
                "asked": "you asked",
                "not_asked": "not asked",
                "quote_not_found": "⚠ quote not found · off",
                "inherited": "approved in epic",
            }.get(provenance, provenance)
            bits = f"🧠 {names}" if names else "🧠"
            quote_raw = memory.get("quote")
            quote = (
                quote_raw.strip()
                if isinstance(quote_raw, str) and quote_raw.strip()
                else ""
            )
            if provenance == "quote_not_found":
                if chip:
                    bits += f" · {chip}"
            elif provenance == "asked" and quote:
                bits += f" · you asked: {quote!r}"
            else:
                if chip:
                    bits += f" · {chip}"
                if quote:
                    bits += f" · you asked: {quote!r}"
            if _memory_is_new(memory):
                bits += " · new"
            line += f"   {bits}"
        lines.append(line)
    try:
        summary = summary_binding(sheet, verdict, "full")
    except Exception:
        summary = ""
    cleaned = summary.strip()
    if cleaned:
        if not cleaned.startswith("→"):
            cleaned = f"→ {cleaned}"
        lines.append(f"  {cleaned}")
    if dry_run:
        lines.append("nothing was approved (dry run)")
    return lines


__all__ = [
    "BOOL_FALSE_WORDS",
    "BOOL_TRUE_WORDS",
    "DecideError",
    "already_approved_decide_error",
    "caller_for_decide",
    "decision_card_lines",
    "direct_card_lines",
    "parse_decide_assignments",
    "resolve_decide_values",
    "resolve_direct_decisions",
    "retry_line_for_plan",
    "verdict_for_kind",
]
