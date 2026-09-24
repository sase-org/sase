"""Miss diagnosis for name-first pending-plan selectors.

Kept apart from :mod:`sase.main.plan_pending` so the resolver stays small.
Every miss ends with the **Awaiting approval** list (or its empty form),
and error codes stay stable: ``conflict_already_handled``, ``gone_stale``,
and ``not_found``.
"""

from __future__ import annotations

import difflib
from pathlib import Path
from typing import TYPE_CHECKING

from sase.plan_names import normalize_selector, plan_name

if TYPE_CHECKING:
    from sase.main.plan_pending import PendingPlan, PendingPlanMiss


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


def diagnose_located_plan_miss(selector: str, located: Path) -> PendingPlanMiss:
    """Diagnose a selector that names an archived plan file on disk."""
    from sase.main.plan_pending import PendingPlanMiss
    from sase.main.plan_inventory_paths import plan_metadata_for_path

    name = plan_name(located)
    metadata = plan_metadata_for_path(str(located))
    title = metadata.title or name
    entries = _gate_history_for_plan(located)
    if not entries:
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
    newest = entries[0]
    state = str(newest.get("state") or "")
    handled_action = str(newest.get("handled_action") or "").strip().lower()
    age = _relative_age(_as_unix_time(newest.get("created_at_unix")))
    if state == "already_handled" and handled_action:
        phrase = _HANDLED_PHRASES.get(handled_action, f"was already {handled_action}")
        return PendingPlanMiss(
            selector=selector,
            header=f"{name} is not awaiting approval",
            detail_lines=(
                f"{title}",
                f"{located}",
                f"This plan {phrase}{age}.",
                f"Inspect it with: sase plan show {name}",
            ),
            suggestions=(),
        )
    if state == "stale" or _entry_is_past_deadline(newest):
        return PendingPlanMiss(
            selector=selector,
            header=f"{name} is not awaiting approval",
            detail_lines=(
                f"{title}",
                f"{located}",
                f"This plan's approval request expired{age} (requests go stale "
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
            f"Inspect it with: sase plan show {name}",
        ),
        suggestions=(),
    )


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


def _locate_named_plan(selector: str) -> Path | None:
    """Locate the archived plan a selector names, if it exists on disk."""
    text = selector.strip()
    candidate = Path(text).expanduser()
    if not candidate.is_absolute():
        candidate = Path.cwd() / candidate
    if candidate.is_file():
        return candidate
    normalized = normalize_selector(text)
    if not normalized:
        return None
    ref_path = _resolve_plan_ref(normalized)
    if ref_path is not None:
        return ref_path
    lowered = normalized.lower()
    matches: list[Path] = []
    try:
        from sase.main.plan_inventory_paths import archived_plan_paths
    except Exception:
        return None
    try:
        archived = archived_plan_paths()
    except Exception:
        return None
    for archived_path in archived:
        stem = archived_path.stem
        if lowered in {stem.lower(), _shard_prefixed(archived_path).lower()}:
            matches.append(archived_path)
    if len(matches) == 1:
        return matches[0]
    return None


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


def _gate_history_for_plan(plan_path: Path) -> list[dict[str, object]]:
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
