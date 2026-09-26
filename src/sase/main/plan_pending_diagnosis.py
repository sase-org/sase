"""Miss diagnosis for name-first pending-plan selectors.

Kept apart from :mod:`sase.main.plan_pending` so the resolver stays small.
Every miss ends with the **Awaiting approval** list (or its empty form),
and error codes stay stable: ``conflict_already_handled``, ``gone_stale``,
and ``not_found``.
"""

from __future__ import annotations

import difflib
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Literal

from sase.plan_names import normalize_selector, plan_name

if TYPE_CHECKING:
    from sase.main.plan_pending import PendingPlan, PendingPlanMiss

PlanGateHistoryKind = Literal["none", "orphaned", "expired", "handled", "direct"]


@dataclass(frozen=True)
class PlanGateHistory:
    """Classified gate history for one located plan file."""

    kind: PlanGateHistoryKind
    action: str | None = None
    age: str = ""
    notification_id: str | None = None
    bundle_path: Path | None = None
    action_data: dict[str, str] | None = None


_HANDLED_PHRASES = {
    "tale": "was already approved as a tale",
    "epic": "was already approved as an epic",
    "approve": "was already approved",
    "commit": "was already approved and committed",
    "reject": "was already rejected",
    "feedback": "was already sent back for revision",
    "revise": "was already sent back for revision",
    "cancelled": "was already cancelled",
    "cancel": "was already cancelled",
}


def diagnose_pending_plan_miss(
    selector: str | None,
    plans: tuple[PendingPlan, ...],
) -> PendingPlanMiss:
    """Build the structured miss for *selector* over pending *plans*."""
    from sase.main.plan_pending import PendingPlanMiss

    if selector is None:
        return PendingPlanMiss(
            selector=None,
            header="no pending plan proposals; pass a selector after running `sase plan list`",
            detail_lines=(),
            suggestions=(),
        )
    located = _locate_named_plan(selector) if selector.strip() else None
    if located is not None:
        return diagnose_located_plan_miss(selector, located)
    return _diagnose_unknown_plan(selector, plans)


def miss_error_code(miss: PendingPlanMiss) -> str:
    """Return the stable error code for a diagnosed miss."""
    text = " ".join((miss.header, *miss.detail_lines))
    if "was already" in text or "was cancelled" in text or "already handled" in text:
        return "conflict_already_handled"
    if "expired" in text or miss.header == "action is stale":
        return "gone_stale"
    return "not_found"


def classify_plan_gate_history(located: Path) -> PlanGateHistory:
    """Classify the gate history for a located plan file.

    Consults the direct-approval receipt first (``direct``), then the
    pending-action store history. Never raises: unreadable stores classify
    as ``none``.
    """
    try:
        from sase.plan_approval_receipts import read_direct_approval_receipt
    except Exception:
        read_direct_approval_receipt = None  # type: ignore[assignment]
    if read_direct_approval_receipt is not None:
        try:
            receipt = read_direct_approval_receipt(located)
        except Exception:
            receipt = None
        if receipt is not None:
            return PlanGateHistory(
                kind="direct",
                action=receipt.action,
                age=_relative_age(_parse_approved_at(receipt.approved_at)),
                notification_id=receipt.retired_gate_id,
            )
    entries = gate_history_for_plan(located)
    if not entries:
        return PlanGateHistory(kind="none")
    newest = entries[0]
    state = str(newest.get("state") or "")
    handled_action = str(newest.get("handled_action") or "").strip().lower()
    age = _relative_age(
        _as_unix_time(newest.get("handled_at_unix"))
        or _as_unix_time(newest.get("created_at_unix"))
    )
    notification_id = _entry_notification_id(newest)
    bundle_path = _entry_bundle_path(newest)
    action_data = _entry_action_data(newest)
    if state == "already_handled" and handled_action:
        return PlanGateHistory(
            kind="handled",
            action=handled_action,
            age=age,
            notification_id=notification_id,
            bundle_path=bundle_path,
            action_data=action_data,
        )
    if state == "stale" or _entry_is_past_deadline(newest):
        return PlanGateHistory(
            kind="expired",
            age=age,
            notification_id=notification_id,
            bundle_path=bundle_path,
            action_data=action_data,
        )
    return PlanGateHistory(
        kind="orphaned",
        notification_id=notification_id,
        bundle_path=bundle_path,
        action_data=action_data,
    )


def diagnose_located_plan_miss(selector: str, located: Path) -> PendingPlanMiss:
    """Diagnose a selector that names an archived plan file on disk."""
    from sase.main.plan_pending import PendingPlanMiss
    from sase.main.plan_inventory_paths import plan_metadata_for_path

    name = plan_name(located)
    metadata = plan_metadata_for_path(str(located))
    title = metadata.title or name
    history = classify_plan_gate_history(located)
    inspect_command = inspect_command_for_located_plan(located, history)
    if history.kind == "direct":
        action = (history.action or "tale").strip() or "tale"
        via = direct_approval_via_text(located)
        return PendingPlanMiss(
            selector=selector,
            header=f"{name} is not awaiting approval",
            detail_lines=(
                f"{title}",
                f"{located}",
                f"This plan was already approved as a {action} {via}{history.age}.",
                f"Inspect it with: {inspect_command}",
            ),
            suggestions=(),
        )
    if history.kind == "none":
        return PendingPlanMiss(
            selector=selector,
            header=f"{name} is not awaiting approval",
            detail_lines=(
                f"{title}",
                f"{located}",
                "No approval gate was ever opened for this plan, so there is "
                "nothing to approve.",
                f"Inspect it with: sase plan show {name}",
            ),
            suggestions=(),
        )
    if history.kind == "handled" and history.action:
        handled_action = (
            refined_gate_history_action(history) or history.action.strip().lower()
        )
        phrase = _HANDLED_PHRASES.get(handled_action, f"was already {handled_action}")
        age = history.age
        return PendingPlanMiss(
            selector=selector,
            header=f"{name} is not awaiting approval",
            detail_lines=(
                f"{title}",
                f"{located}",
                f"This plan {phrase}{age}.",
                f"Inspect it with: {inspect_command}",
            ),
            suggestions=(),
        )
    if history.kind == "expired":
        return PendingPlanMiss(
            selector=selector,
            header=f"{name} is not awaiting approval",
            detail_lines=(
                f"{title}",
                f"{located}",
                f"This plan's approval request expired{history.age} (requests go stale "
                "after 24h).",
                f"Inspect it with: sase plan show {name}",
            ),
            suggestions=(),
        )
    # Available in the store but owned by no live gate shell or planner.
    return PendingPlanMiss(
        selector=selector,
        header=f"{name} is not awaiting approval",
        detail_lines=(
            f"{title}",
            f"{located}",
            "Its approval gate is orphaned: no live gate shell or planner owns it.",
            f"Inspect it with: {inspect_command}",
        ),
        suggestions=(),
    )


def refined_gate_history_action(history: PlanGateHistory) -> str | None:
    """Return the real approval action for a handled gate history, if known.

    The pending-action store records the protocol action (shared by tale,
    approve, and commit); the gate bundle's ``response.json`` records the real
    choice. Falls back to ``None`` when the bundle cannot be read.
    """
    bundle_path = getattr(history, "bundle_path", None)
    if bundle_path is None:
        return None
    action, _ref = _gate_approval_facts(Path(bundle_path))
    return action


def gate_history_committed_ref(history: PlanGateHistory) -> str | None:
    """Return the committed ``plan:`` ref a handled gate approval produced."""
    bundle_path = getattr(history, "bundle_path", None)
    if bundle_path is None:
        return None
    _action, ref = _gate_approval_facts(Path(bundle_path))
    return ref


def _gate_approval_facts(bundle_path: Path) -> tuple[str | None, str | None]:
    """Return ``(real action, committed ref)`` from a gate bundle response.

    Best-effort; never raises. The action refines the stored protocol action
    through ``response.json``; the ref is the primary option result's
    ``plan_archive_ref``.
    """
    try:
        import json

        response_path = bundle_path / "response.json"
        raw = json.loads(response_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, ValueError):
        return None, None
    if not isinstance(raw, dict):
        return None, None
    try:
        from sase._plan_gate_envelope import translate_plan_gate_response
        from sase._plan_approval_protocol import persisted_plan_action
    except Exception:
        return None, None
    try:
        translated = translate_plan_gate_response(bundle_path, raw)
    except Exception:
        return None, None
    action = persisted_plan_action(translated)
    ref = translated.get("plan_archive_ref")
    committed = ref.strip() if isinstance(ref, str) and ref.strip() else None
    return action, committed


def inspect_command_for_located_plan(
    located: Path, history: PlanGateHistory | None = None
) -> str:
    """Return a ``sase plan show`` command that resolves to exactly one plan.

    Uses the committed ``plan:`` ref when the approval committed the plan,
    otherwise the absolute local plan path, so the selector never stays
    ambiguous between the local proposal and the committed copy.
    """
    if history is not None:
        if history.kind == "handled":
            committed = gate_history_committed_ref(history)
            if committed:
                return f"sase plan show {committed}"
        elif history.kind == "direct":
            committed = _receipt_committed_ref(located)
            if committed:
                return f"sase plan show {committed}"
    try:
        absolute = str(located.expanduser().resolve(strict=False))
    except Exception:
        absolute = str(located)
    return f"sase plan show {absolute}"


def _receipt_committed_ref(located: Path) -> str | None:
    try:
        from sase.plan_approval_receipts import read_direct_approval_receipt

        receipt = read_direct_approval_receipt(located)
    except Exception:
        return None
    if receipt is None or not receipt.plan_archive_ref:
        return None
    return receipt.plan_archive_ref


def direct_approval_via_text(located: Path) -> str:
    """Return the via-phrase for a direct-approval history line."""
    try:
        from sase.plan_approval_receipts import read_direct_approval_receipt

        receipt = read_direct_approval_receipt(located)
    except Exception:
        receipt = None
    if receipt is not None and (receipt.replaced_coders or receipt.recovered_gate_id):
        return "coder relaunched via sase plan approve"
    return "via sase plan approve"


def _diagnose_unknown_plan(
    selector: str, plans: tuple[PendingPlan, ...]
) -> PendingPlanMiss:
    from sase.main.plan_pending import PendingPlanMiss

    names = [plan.display_name for plan in plans if plan.display_name]
    suggestions = difflib.get_close_matches(selector.strip(), names, n=3, cutoff=0.6)
    detail = tuple(f"did you mean: {suggestion}" for suggestion in suggestions)
    return PendingPlanMiss(
        selector=selector,
        header=f"no pending plan matches `{selector.strip()}`",
        detail_lines=detail,
        suggestions=tuple(suggestions),
    )


def locate_plan_candidates(selector: str) -> tuple[Path, ...]:
    """Return every plan file *selector* names, in priority order.

    Generalization of the old single-match lookup: paths first, then
    ``plan:``/``<shard>/<name>`` refs, then exact archived-name matches,
    then notification IDs/prefixes of unavailable PlanApproval notifications
    mapped back to their plan file. Empty when nothing matches.
    """
    text = selector.strip()
    if not text:
        return ()
    candidate = Path(text).expanduser()
    if not candidate.is_absolute():
        candidate = Path.cwd() / candidate
    if candidate.is_file():
        return (candidate,)
    normalized = normalize_selector(text)
    if not normalized:
        return ()
    ref_path = _resolve_plan_ref(normalized)
    if ref_path is not None:
        return (ref_path,)
    lowered = normalized.lower()
    try:
        from sase.main.plan_inventory_paths import archived_plan_paths
    except Exception:
        archived: tuple[Path, ...] = ()
    else:
        try:
            archived = archived_plan_paths()
        except Exception:
            archived = ()
    matches = [
        archived_path
        for archived_path in archived
        if lowered
        in {archived_path.stem.lower(), _shard_prefixed(archived_path).lower()}
    ]
    if matches:
        return tuple(matches)
    mapped = _plan_file_for_notification_selector(text)
    if mapped is not None:
        return (mapped,)
    return ()


def _locate_named_plan(selector: str) -> Path | None:
    """Locate the archived plan a selector names, if it exists on disk."""
    matches = locate_plan_candidates(selector)
    if len(matches) == 1:
        return matches[0]
    return None


def _plan_file_for_notification_selector(selector: str) -> Path | None:
    """Map a notification ID/prefix of an unavailable proposal to its file."""
    text = selector.strip()
    if not text:
        return None
    try:
        from sase.notifications.store import load_notifications
    except Exception:
        return None
    try:
        notifications = load_notifications(include_dismissed=True)
    except Exception:
        return None
    from sase.plan_approval_actions import PLAN_APPROVAL_ACTIONS

    matches = [
        notification
        for notification in notifications
        if notification.action in PLAN_APPROVAL_ACTIONS
        and (notification.id == text or notification.id.startswith(text))
    ]
    if len(matches) != 1:
        return None
    notification = matches[0]
    try:
        from sase.plan_approval_actions import (
            PlanApprovalActionContext,
            durable_plan_file_for_context,
        )
    except Exception:
        return None
    context = PlanApprovalActionContext(
        id=notification.id,
        host_files=tuple(notification.files),
        host_action_data=dict(notification.action_data),
    )
    try:
        resolved = durable_plan_file_for_context(context)
    except Exception:
        return None
    return resolved


def _entry_notification_id(entry: dict[str, object]) -> str | None:
    value = entry.get("notification_id")
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _entry_bundle_path(entry: dict[str, object]) -> Path | None:
    action_data = entry.get("action_data")
    if isinstance(action_data, dict):
        for key in ("bundle_path", "response_dir"):
            raw = action_data.get(key)
            if isinstance(raw, str) and raw.strip():
                return Path(raw.strip()).expanduser()
    return None


def _entry_action_data(entry: dict[str, object]) -> dict[str, str] | None:
    action_data = entry.get("action_data")
    if not isinstance(action_data, dict):
        return None
    cleaned = {
        str(key): str(value)
        for key, value in action_data.items()
        if isinstance(key, str) and isinstance(value, str)
    }
    return cleaned or None


def _parse_approved_at(value: str) -> float:
    from datetime import datetime

    try:
        parsed = datetime.fromisoformat(value.strip())
    except (ValueError, AttributeError):
        return 0.0
    try:
        return parsed.timestamp()
    except (OverflowError, OSError, ValueError):
        return 0.0


def _resolve_plan_ref(normalized: str) -> Path | None:
    """Resolve ``plan:``/``<shard>/<name>`` spellings through Rust plan refs."""
    candidates = [f"plan:{normalized}"]
    if "/" not in normalized:
        return None
    try:
        from sase.sdd.plan_refs import (
            resolve_plan_reference_from_roots,
            resolve_plan_roots,
            workspace_context_for_plan_resolution,
        )
    except Exception:
        return None
    try:
        cwd = Path.cwd()
        workspace_dir, workspace_num = workspace_context_for_plan_resolution(cwd)
        roots = resolve_plan_roots(workspace_dir, workspace_num)
        for candidate in candidates:
            resolution = resolve_plan_reference_from_roots(candidate, roots=roots)
            if resolution.status in ("exact", "drifted"):
                return resolution.resolved_path
    except Exception:
        return None
    return None


def gate_history_for_plan(plan_path: Path) -> list[dict[str, object]]:
    """Return pending-action entries for *plan_path*, newest first."""
    try:
        from sase.notifications.pending_actions import read_pending_action_store
    except Exception:
        return []
    try:
        store = read_pending_action_store(include_legacy=True)
    except Exception:
        return []
    try:
        resolved = plan_path.expanduser().resolve(strict=False)
    except Exception:
        return []
    entries = []
    actions = store.get("actions", {})
    if not isinstance(actions, dict):
        return []
    for entry in actions.values():
        if not isinstance(entry, dict):
            continue
        action_data = entry.get("action_data")
        if not isinstance(action_data, dict):
            continue
        raw = action_data.get("original_plan_file")
        if not isinstance(raw, str) or not raw:
            continue
        try:
            entry_path = Path(raw).expanduser().resolve(strict=False)
        except Exception:
            continue
        if entry_path == resolved:
            entries.append(entry)
    entries.sort(key=_entry_sort_key, reverse=True)
    return entries


def _entry_sort_key(entry: dict[str, object]) -> float:
    return _as_unix_time(entry.get("created_at_unix"))


def _as_unix_time(value: object) -> float:
    if isinstance(value, bool):
        return 0.0
    if isinstance(value, (int, float)):
        return float(value)
    return 0.0


def _entry_is_past_deadline(entry: dict[str, object]) -> bool:
    import time

    deadline = _as_unix_time(entry.get("stale_deadline_unix"))
    return deadline > 0.0 and deadline <= time.time()


def _relative_age(created_at_unix: float) -> str:
    if created_at_unix <= 0:
        return ""
    import time

    age_seconds = int(time.time() - created_at_unix)
    if age_seconds < 0:
        return ""
    if age_seconds < 60:
        return f" ({age_seconds}s ago)"
    minutes = age_seconds // 60
    if minutes < 60:
        return f" ({minutes}m ago)"
    hours = minutes // 60
    if hours < 48:
        return f" ({hours}h ago)"
    return f" ({hours // 24}d ago)"


def _shard_prefixed(path: Path) -> str:
    parts = path.parts
    if len(parts) >= 2 and len(parts[-2]) == 6 and parts[-2].isdigit():
        return f"{parts[-2]}/{path.stem}"
    return path.stem
