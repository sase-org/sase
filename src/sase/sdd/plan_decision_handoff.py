"""Deliver accepted Plan Decisions to coders, beads, and receipts (sase-1hi.4).

This module is the handoff leg of the ``plan_decisions`` feature. It reads the
host-stamped durable plan (``answer``/``decided_by``/``decided_via`` written by
:mod:`sase.plan_gate_stamp`), renders the core-owned implementer block for tale
coders, resolves an epic's accepted sheet for phase and land agents, and posts
the quiet ``%auto`` receipt notification.

Every entry point fails open to "no decisions output": an unstamped plan or an
unresolvable epic context yields ``None``/``""``/``False`` and never breaks the
caller (coder launch, ``bead read``, gate execution).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sase.sdd._plan_display_decisions import (
    format_decision_value,
    memory_note_names,
    provenance_chip,
)

RECEIPT_TAG = "plan_decisions_receipt"

_TALE_CODER_AUDIENCE = "tale_coder"
_EPIC_PHASE_AUDIENCE = "epic_phase"
_EPIC_LAND_AUDIENCE = "epic_land"


@dataclass(frozen=True)
class StampedDecisions:
    """One plan file's decisions with its accepted (or pending) answers."""

    sheet: dict[str, Any]
    decided_by: str | None
    decided_via: str | None
    values: dict[str, Any]
    title: str
    tier: str


@dataclass(frozen=True)
class EpicDecisionContext:
    """An epic's accepted sheet, for inheritance into phase sub-plans."""

    sheet: dict[str, Any]
    epic_title: str
    decided_by: str
    decided_via: str | None

    def inherited_wire(self) -> dict[str, Any]:
        """Return the ``inherited`` record the core prompt-block takes."""
        return {"sheet": self.sheet, "epic_title": self.epic_title}


def _frontmatter_tier(path: Path) -> str:
    try:
        from sase.sdd.frontmatter import parse_frontmatter

        frontmatter, _body, had = parse_frontmatter(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError):
        return "tale"
    if had and str(frontmatter.get("tier") or "").strip().lower() == "epic":
        return "epic"
    return "tale"


def load_stamped_decisions(
    plan_path: str | Path, tier: str | None = None
) -> StampedDecisions | None:
    """Load a plan file's decisions and build its Decision Sheet.

    Returns ``None`` when the plan has no ``decisions:`` map or anything fails
    to resolve. Both stamped (accepted) and unstamped (pending) plans load;
    ``decided_by`` is ``None`` for pending plans.
    """
    try:
        from sase.sdd.plan_decisions import (
            build_definitions,
            sheet_binding,
        )
        from sase.sdd.plan_validate import validate_plan_file
    except Exception:
        return None
    try:
        path = Path(str(plan_path)).expanduser()
        if not path.is_file():
            return None
        resolved_tier = tier or _frontmatter_tier(path)
        if resolved_tier not in ("tale", "epic"):
            resolved_tier = "tale"
        validation = validate_plan_file(path, resolved_tier, mode="launch")
    except Exception:
        return None
    try:
        plan = getattr(validation, "plan", None)
        if plan is None or not getattr(plan, "decisions", ()):
            return None
        definitions = build_definitions(validation, "")
        values = {
            str(decision.id): decision.answer
            for decision in plan.decisions
            if getattr(decision, "answer", None) is not None
        }
        for definition in definitions:
            decision_id = str(definition.get("id", ""))
            if decision_id and decision_id not in values:
                values[decision_id] = definition.get(
                    "effective_default", definition.get("default")
                )
        sheet = sheet_binding(definitions, values)
    except Exception:
        return None
    return StampedDecisions(
        sheet=sheet,
        decided_by=getattr(plan, "decided_by", None),
        decided_via=getattr(plan, "decided_via", None),
        values=values,
        title=str(getattr(plan, "title", None) or path.stem),
        tier=resolved_tier,
    )


def coder_decisions_block(
    plan_path: str | Path,
    *,
    tier: str | None = None,
    audience: str = _TALE_CODER_AUDIENCE,
    inherited: EpicDecisionContext | None = None,
) -> str:
    """Render the host-written Reviewer decisions block for a coder prompt.

    Returns ``""`` when the plan carries no accepted decisions. Only stamped
    answers (``decided_by`` set) produce a block: pending plans have nothing
    final to hand a coder.
    """
    try:
        from sase.sdd.plan_decisions import prompt_block_binding
    except Exception:
        return ""
    stamped = load_stamped_decisions(plan_path, tier)
    if stamped is None or stamped.decided_by is None:
        return ""
    if audience not in (
        _TALE_CODER_AUDIENCE,
        _EPIC_PHASE_AUDIENCE,
        _EPIC_LAND_AUDIENCE,
    ):
        audience = _TALE_CODER_AUDIENCE
    try:
        return prompt_block_binding(
            stamped.sheet,
            stamped.decided_by,
            stamped.decided_via,
            audience,
            inherited.inherited_wire() if inherited is not None else None,
        )
    except Exception:
        return ""


def _epic_plan_candidates(meta: dict[str, Any]) -> list[str]:
    """Return epic plan file candidates from agent metadata, best first."""
    candidates: list[str] = []
    for key in ("epic_plan_snapshot", "epic_plan_ref"):
        value = meta.get(key)
        if isinstance(value, str) and value.strip():
            candidates.append(value.strip())
    return candidates


def _resolve_plan_file(candidate: str) -> Path | None:
    """Resolve an epic plan ref to an existing file, else ``None`` (closed)."""
    text = candidate.strip()
    if text.startswith("@"):
        text = text[1:]
    path = Path(text).expanduser()
    if path.is_file():
        return path
    return None


def epic_decision_context(artifacts_dir: str | Path) -> EpicDecisionContext | None:
    """Resolve a phase or land agent's epic to its accepted decision sheet.

    Reads ``epic_plan_snapshot`` (frozen at launch) then ``epic_plan_ref`` from
    the agent's ``agent_meta.json``. Fails closed: anything unresolvable —
    missing metadata, missing file, unstamped or decision-free epic plan —
    yields ``None`` and the caller inherits nothing.
    """
    import json

    try:
        meta_path = Path(str(artifacts_dir)).expanduser() / "agent_meta.json"
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError):
        return None
    if not isinstance(meta, dict):
        return None
    for candidate in _epic_plan_candidates(meta):
        plan_file = _resolve_plan_file(candidate)
        if plan_file is None:
            continue
        stamped = load_stamped_decisions(plan_file, "epic")
        if stamped is None or stamped.decided_by is None:
            continue
        return EpicDecisionContext(
            sheet=stamped.sheet,
            epic_title=stamped.title,
            decided_by=stamped.decided_by,
            decided_via=stamped.decided_via,
        )
    return None


def _receipt_notes(
    plan_label: str, sheet: dict[str, Any], auto: bool = True
) -> list[str]:
    """Build the quiet ``%auto`` receipt lines from an accepted sheet."""
    rows = sheet.get("rows")
    if not isinstance(rows, list):
        rows = []
    reviewer = " (auto)" if auto else ""
    lines = [f"\U0001f916 Auto-approved {plan_label}"]
    for row in rows:
        if not isinstance(row, dict):
            continue
        decision_id = str(row.get("id", ""))
        value = row.get("value")
        changed = bool(row.get("changed"))
        memory = row.get("memory")
        if isinstance(memory, dict):
            lines.extend(_receipt_memory_lines(decision_id, value, changed, memory))
            continue
        marker = " \u25cf" if changed else " \u2605"
        lines.append(
            f"{decision_id} = {format_decision_value(value)}{marker}{reviewer}"
        )
    return lines


def _receipt_memory_lines(
    decision_id: str, value: Any, changed: bool, memory: dict[str, Any]
) -> list[str]:
    """Build receipt lines for one memory decision row."""
    names = memory_note_names(memory) or [decision_id]
    provenance = str(memory.get("provenance") or "")
    quote = memory.get("quote")
    quote_text = str(quote).strip() if isinstance(quote, str) else ""
    note_names = ", ".join(names)
    if value is True:
        chip = provenance_chip(provenance)
        detail = f"you asked: {quote_text!r}" if quote_text else (chip or "on")
        return [f"\U0001f9e0 {note_names} \u00b7 {detail}"]
    if provenance in ("not_asked", "quote_not_found"):
        return [
            f"\u26a0 \U0001f9e0 {decision_id} = no \u00b7 not asked "
            "\u2014 left off because no human reviewed this plan"
        ]
    marker = " \u25cf" if changed else ""
    shown = format_decision_value(value)
    return [f"\U0001f9e0 {decision_id} = {shown}{marker}"]


def post_auto_approval_receipt(
    *,
    request_id: str,
    plan_label: str,
    sheet: dict[str, Any],
) -> bool:
    """Post the quiet ``%auto`` receipt notification for an auto-approval.

    The receipt is informational, never a gate: ``action=None`` so no pending
    action (and no toast) is registered, and ``silent=True`` keeps it as a
    plain inbox row with no unread bump. The stable tag lets surfaces filter
    it, and the per-request dedup key makes re-settlement idempotent. Telegram
    can forward it quietly because it carries no action and no gate state.
    """
    rows = sheet.get("rows")
    if not isinstance(rows, list) or not rows:
        return False
    if not request_id.strip() or not plan_label.strip():
        return False
    try:
        from datetime import datetime
        from uuid import uuid4

        from sase.core.time import get_timezone
        from sase.notifications.models import Notification
        from sase.notifications.store import upsert_notification

        notification = Notification(
            id=str(uuid4()),
            timestamp=datetime.now(get_timezone()).isoformat(),
            sender="plan-decisions",
            notes=_receipt_notes(plan_label.strip(), sheet),
            tags=[RECEIPT_TAG],
            silent=True,
            action=None,
            dedup_key=f"plan-decisions-receipt-{request_id.strip()}",
        )
        upsert_notification(notification, plus_one_note="re-settled")
    except Exception:
        return False
    return True


__all__ = [
    "EpicDecisionContext",
    "RECEIPT_TAG",
    "StampedDecisions",
    "coder_decisions_block",
    "epic_decision_context",
    "load_stamped_decisions",
    "post_auto_approval_receipt",
]
