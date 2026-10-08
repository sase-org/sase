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


def _synthetic_accepted_definitions(plan: Any) -> list[dict[str, Any]]:
    """Build neutral accepted definitions from authored decisions and answers.

    Each definition uses the authored ``default`` as ``effective_default``
    (no clamping), copies ``ask``, choice keys/labels, ``why``, and memory
    selectors, leaves ``resolved`` empty, and omits ``provenance`` so no
    chip or warning appears.
    """
    definitions: list[dict[str, Any]] = []
    for decision in getattr(plan, "decisions", ()):
        decision_id = str(getattr(decision, "id", "") or "")
        if not decision_id:
            continue
        choices = [
            {"key": str(choice.key), "label": str(choice.label)}
            for choice in getattr(decision, "choices", ())
        ]
        kind = str(getattr(decision, "kind", "") or "")
        if kind not in ("choice", "toggle"):
            kind = "choice" if choices else "toggle"
        default = getattr(decision, "default", None)
        entry: dict[str, Any] = {
            "id": decision_id,
            "kind": kind,
            "ask": str(getattr(decision, "ask", "") or ""),
            "default": default,
            "effective_default": default,
            "resolved": [],
        }
        why = getattr(decision, "why", None)
        if why is not None:
            entry["why"] = why
        if choices:
            entry["choices"] = choices
        memory = getattr(decision, "memory", None)
        if memory is not None:
            try:
                selectors = [str(item) for item in memory]
            except TypeError:
                selectors = []
            entry["memory"] = {"selectors": selectors}
        definitions.append(entry)
    return definitions


def load_stamped_decisions(
    plan_path: str | Path, tier: str | None = None
) -> StampedDecisions | None:
    """Load a plan file's decisions and build its Decision Sheet.

    Returns ``None`` when the plan has no ``decisions:`` map or anything fails
    to resolve. Both stamped (accepted) and unstamped (pending) plans load;
    ``decided_by`` is ``None`` for pending plans.

    Accepted plans (``decided_by`` set) never touch the reader's environment:
    they render from the frozen sibling, else from a neutral synthesis of the
    authored map plus stamped answers. Pending plans keep the live
    ``build_definitions`` path.
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
        decided_by = getattr(plan, "decided_by", None)
        if decided_by is not None:
            from sase.sdd.plan_decision_freeze import read_frozen_definitions

            try:
                frozen = read_frozen_definitions(path)
            except Exception:
                frozen = None
            definitions = frozen if frozen else _synthetic_accepted_definitions(plan)
            if not definitions:
                return None
        else:
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


def _agent_plan_roots(meta: dict[str, Any]) -> tuple[Path, ...]:
    """Return the agent's project plan roots, best effort, never raising."""
    roots: list[Path] = []
    try:
        from sase.bead.cli_detail_context import plan_reference_roots
        from sase.sdd.plan_refs import (
            resolve_plan_roots,
            workspace_context_for_plan_resolution,
        )

        try:
            roots.extend(plan_reference_roots())
        except Exception:
            pass
        for key in (
            "agent_project_file",
            "project_file",
            "project_dir",
            "workspace_dir",
            "workspace",
        ):
            raw = meta.get(key)
            if not isinstance(raw, str) or not raw.strip():
                continue
            try:
                candidate = Path(raw.strip()).expanduser()
                base = candidate.parent if candidate.suffix else candidate
                workspace_dir, workspace_num = workspace_context_for_plan_resolution(
                    base
                )
                for root in resolve_plan_roots(workspace_dir, workspace_num):
                    if root not in roots:
                        roots.append(root)
            except Exception:
                continue
    except Exception:
        pass
    return tuple(roots)


def _resolve_plan_file(candidate: str, *, roots: tuple[Path, ...] = ()) -> Path | None:
    """Resolve an epic plan ref to an existing file, else ``None`` (closed)."""
    text = candidate.strip()
    if text.startswith("@"):
        text = text[1:]
    if not text:
        return None
    path = Path(text).expanduser()
    if path.is_file():
        return path
    if roots:
        try:
            from sase.sdd.plan_refs import resolve_plan_reference_from_roots

            resolution = resolve_plan_reference_from_roots(text, roots=roots)
            resolved = getattr(resolution, "resolved_path", None)
            if resolved is not None and Path(str(resolved)).is_file():
                return Path(str(resolved))
        except Exception:
            pass
    return None


def _read_agent_meta(artifacts_dir: str | Path) -> dict[str, Any] | None:
    """Return an artifacts dir's agent metadata dict, else ``None``."""
    import json as _json

    try:
        meta_path = Path(str(artifacts_dir)).expanduser() / "agent_meta.json"
        meta = _json.loads(meta_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError):
        return None
    return meta if isinstance(meta, dict) else None


def _bead_design_plan(bead_id: str) -> str | None:
    """Return a bead's design plan string via the bead-read store API."""
    raw = str(bead_id or "").strip()
    if not raw:
        return None
    try:
        from sase.bead.cli_common import get_read_view
        from sase.bead.cli_detail_resolution import resolve_issue_detail
    except Exception:
        return None
    try:
        with get_read_view() as view:
            detail = resolve_issue_detail(view, raw, include_links=False)
    except Exception:
        return None
    try:
        plan = getattr(detail, "plan", None)
        path = str(getattr(plan, "path", "") or "").strip()
        return path or None
    except Exception:
        return None


def _stamped_epic_from_design(
    design: str | None, *, roots: tuple[Path, ...]
) -> EpicDecisionContext | None:
    """Resolve one design plan string to its stamped epic sheet, if accepted."""
    if not design or not design.strip():
        return None
    plan_file = _resolve_plan_file(design.strip(), roots=roots)
    if plan_file is None:
        return None
    try:
        stamped = load_stamped_decisions(plan_file, "epic")
    except Exception:
        return None
    if stamped is None or stamped.decided_by is None:
        return None
    return EpicDecisionContext(
        sheet=stamped.sheet,
        epic_title=stamped.title,
        decided_by=stamped.decided_by,
        decided_via=stamped.decided_via,
    )


def _epic_context_from_meta(meta: dict[str, Any]) -> EpicDecisionContext | None:
    """Resolve an epic sheet from one agent meta, in order, else ``None``."""
    roots = _agent_plan_roots(meta)
    snapshot = meta.get("epic_plan_snapshot")
    if isinstance(snapshot, str) and snapshot.strip():
        direct = Path(snapshot.strip().lstrip("@")).expanduser()
        if direct.is_file():
            try:
                stamped = load_stamped_decisions(direct, "epic")
            except Exception:
                stamped = None
            if stamped is not None and stamped.decided_by is not None:
                return EpicDecisionContext(
                    sheet=stamped.sheet,
                    epic_title=stamped.title,
                    decided_by=stamped.decided_by,
                    decided_via=stamped.decided_via,
                )
    ref = meta.get("epic_plan_ref")
    if isinstance(ref, str) and ref.strip():
        found = _stamped_epic_from_design(ref.strip(), roots=roots)
        if found is not None:
            return found
    phase_bead_id = meta.get("phase_bead_id")
    if isinstance(phase_bead_id, str) and phase_bead_id.strip():
        try:
            from sase.bead.cli_common import get_read_view
            from sase.bead.cli_detail_resolution import resolve_issue_detail
        except Exception:
            phase_detail = None
        else:
            try:
                with get_read_view() as view:
                    phase_detail = resolve_issue_detail(
                        view, phase_bead_id.strip(), include_links=False
                    )
            except Exception:
                phase_detail = None
        if phase_detail is not None:
            try:
                issue = getattr(phase_detail, "issue", None)
                parent_id = str(getattr(issue, "parent_id", "") or "").strip()
            except Exception:
                parent_id = ""
            if parent_id:
                design = _bead_design_plan(parent_id)
                found = _stamped_epic_from_design(design, roots=roots)
                if found is not None:
                    return found
    epic_bead_id = meta.get("epic_bead_id")
    if isinstance(epic_bead_id, str) and epic_bead_id.strip():
        design = _bead_design_plan(epic_bead_id.strip())
        found = _stamped_epic_from_design(design, roots=roots)
        if found is not None:
            return found
    return None


def _ancestor_metas(
    artifacts_dir: str | Path, head_meta: dict[str, Any]
) -> list[dict[str, Any]]:
    """Return ancestor metas via session parent links, bounded, oldest first."""
    try:
        from sase.sdd.plan_human_text import _MAX_SESSION_LINKS as _bound
    except Exception:
        _bound = 50
    try:
        current = str(Path(str(artifacts_dir)).expanduser().resolve(strict=False))
    except Exception:
        return []
    seen = {current}
    metas: list[dict[str, Any]] = []
    meta: dict[str, Any] = head_meta
    import os as _os

    for _ in range(int(_bound)):
        parent: str | None = None
        for key in ("parent_timestamp", "plan_chain_parent_timestamp"):
            raw = meta.get(key)
            if isinstance(raw, str) and raw.strip():
                stamp = raw.strip()
                if not stamp or "/" in stamp or "\\" in stamp or stamp in (".", ".."):
                    continue
                candidate = _os.path.join(_os.path.dirname(current), stamp)
                try:
                    sibling = _os.path.abspath(candidate)
                except Exception:
                    continue
                if sibling in seen or not _os.path.isdir(sibling):
                    continue
                if not _os.path.isfile(_os.path.join(sibling, "agent_meta.json")):
                    continue
                parent = sibling
                break
        if parent is None:
            break
        seen.add(parent)
        current = parent
        ancestor = _read_agent_meta(parent)
        if not ancestor:
            break
        metas.append(ancestor)
        meta = ancestor
    return metas


def epic_decision_context(artifacts_dir: str | Path) -> EpicDecisionContext | None:
    """Resolve a phase or land agent's epic to its accepted decision sheet.

    Resolves, in order: the launch-time snapshot file, the ``epic_plan_ref``
    through project plan roots, the ``phase_bead_id`` parent epic design, the
    ``epic_bead_id`` design, then the same steps on each session ancestor (so
    a phase planner's coder successor inherits). Fails closed: an unstamped
    epic, a missing bead, a cycle, or an unreadable meta yields ``None``.
    """
    head = _read_agent_meta(artifacts_dir)
    if head is None:
        return None
    seen_markers: set[tuple[str, str, str, str]] = set()
    for meta in [head, *_ancestor_metas(artifacts_dir, head)]:
        try:
            marker = (
                str(meta.get("epic_plan_snapshot") or ""),
                str(meta.get("epic_plan_ref") or ""),
                str(meta.get("phase_bead_id") or ""),
                str(meta.get("epic_bead_id") or ""),
            )
        except Exception:
            marker = ("", "", "", "")
        if marker in seen_markers:
            continue
        seen_markers.add(marker)
        try:
            found = _epic_context_from_meta(meta)
        except Exception:
            found = None
        if found is not None:
            return found
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
