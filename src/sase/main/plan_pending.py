"""Name-first pending plan-approval resolution for the plan CLI commands.

``sase plan approve`` and ``sase plan reject`` resolve PLAN identically:
exact tier first (full notification ID, archive/bundle path, ``name`` or
``<shard>/<name>``, planner agent), then the notification-ID prefix tier.
Miss diagnosis lives in :mod:`sase.main.plan_pending_diagnosis` and shared
rendering in :mod:`sase.main.plan_pending_render`.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from sase.main.plan_candidates import visible_pending_plan_notifications
from sase.main.plan_inventory_paths import plan_metadata_for_path
from sase.main.plan_pending_diagnosis import diagnose_pending_plan_miss
from sase.notifications.models import Notification, format_relative_time
from sase.notifications.pending_actions import action_state_for_notification
from sase.notifications.store import load_notifications
from sase.plan_approval_actions import (
    PLAN_APPROVAL_ACTIONS,
    PlanApprovalActionContext,
    PlanApprovalActionError,
)
from sase.plan_names import normalize_selector, plan_display_names, plan_name


@dataclass(frozen=True)
class PendingPlan:
    """One visible pending plan proposal with its resolved presentation."""

    notification: Notification
    name: str
    display_name: str
    archive_path: str | None
    bundle_plan_path: str | None
    title: str | None
    tier: str
    agent: str
    age: str
    matched_by: str = ""


@dataclass(frozen=True)
class PendingPlanMatch:
    """A selector that resolved to exactly one pending proposal."""

    plan: PendingPlan


@dataclass(frozen=True)
class PendingPlanAmbiguity:
    """A selector that matched more than one pending proposal."""

    selector: str
    candidates: tuple[PendingPlan, ...]


@dataclass(frozen=True)
class PendingPlanMiss:
    """A selector (or omitted PLAN) that matched no pending proposal."""

    selector: str | None
    header: str
    detail_lines: tuple[str, ...]
    suggestions: tuple[str, ...]


def pending_plans() -> tuple[PendingPlan, ...]:
    """Return visible pending proposals newest-first with names resolved."""
    notifications = visible_pending_plan_notifications()
    archive_paths = [_archive_path_for(n) or "" for n in notifications]
    display = plan_display_names(
        [path or n.id for path, n in zip(archive_paths, notifications, strict=True)]
    )
    plans = []
    for notification, archive_path in zip(notifications, archive_paths, strict=True):
        key = archive_path or notification.id
        metadata = plan_metadata_for_path(
            archive_path or _bundle_plan_path_for(notification)
        )
        plans.append(
            PendingPlan(
                notification=notification,
                name=plan_name(archive_path) if archive_path else "",
                display_name=display.get(key, key),
                archive_path=archive_path,
                bundle_plan_path=_bundle_plan_path_for(notification),
                title=metadata.title,
                tier=_tier_for(notification, metadata.tier),
                agent=_agent_for(notification),
                age=format_relative_time(notification.timestamp),
            )
        )
    return tuple(plans)


def resolve_pending_plan_selector(
    raw: str | None,
) -> PendingPlanMatch | PendingPlanAmbiguity | PendingPlanMiss:
    """Resolve PLAN without raising; misses carry their diagnosis."""
    plans = pending_plans()
    if raw is None:
        return _resolve_omitted(plans)
    selector = raw.strip()
    exact = [
        _with_matched_by(plan, how)
        for plan in plans
        if (how := _exact_match_how(selector, plan)) is not None
    ]
    if len(exact) == 1:
        return PendingPlanMatch(plan=exact[0])
    if len(exact) > 1:
        return PendingPlanAmbiguity(selector=selector, candidates=tuple(exact))
    prefixed = [
        _with_matched_by(plan, "ID prefix")
        for plan in plans
        if plan.notification.id.startswith(selector) and selector
    ]
    if len(prefixed) == 1:
        return PendingPlanMatch(plan=prefixed[0])
    if len(prefixed) > 1:
        return PendingPlanAmbiguity(selector=selector, candidates=tuple(prefixed))
    unavailable = _unavailable_id_matches(selector, plans)
    if unavailable is not None:
        return unavailable
    return diagnose_pending_plan_miss(selector, plans)


def resolve_pending_plan(selector: str | None) -> Notification:
    """Resolve the pending PlanApproval notification a selector refers to.

    Raising wrapper around :func:`resolve_pending_plan_selector` using the
    stable error codes, kept for ``plan_show`` and existing callers.
    """
    outcome = resolve_pending_plan_selector(selector)
    if isinstance(outcome, PendingPlanMatch):
        return outcome.plan.notification
    if isinstance(outcome, PendingPlanAmbiguity):
        raise PlanApprovalActionError(
            "ambiguous_prefix", outcome.selector, "action prefix is ambiguous"
        )
    if outcome.selector is None:
        raise PlanApprovalActionError("missing_selector", "selector", outcome.header)
    from sase.main.plan_pending_diagnosis import miss_error_code

    raise PlanApprovalActionError(
        miss_error_code(outcome), outcome.selector, outcome.header
    )


def _resolve_omitted(
    plans: tuple[PendingPlan, ...],
) -> PendingPlanMatch | PendingPlanMiss:
    if len(plans) == 1:
        return PendingPlanMatch(plan=plans[0])
    if not plans:
        return diagnose_pending_plan_miss(None, plans)
    return PendingPlanMiss(
        selector=None,
        header="multiple pending plan proposals; pass a plan name",
        detail_lines=(),
        suggestions=tuple(plan.display_name for plan in plans),
    )


def _exact_match_how(selector: str, plan: PendingPlan) -> str | None:
    """Return the matched-by label when *selector* exactly matches *plan*."""
    notification = plan.notification
    if selector == notification.id:
        return "ID"
    if _selector_resolves_to_path(selector, plan):
        return "path"
    normalized = normalize_selector(selector)
    lowered = normalized.lower()
    if not lowered:
        return None
    candidates = {plan.name.lower()}
    if plan.archive_path:
        shard_name = _shard_prefixed_name(plan.archive_path)
        if shard_name:
            candidates.add(shard_name.lower())
    if lowered in candidates:
        return "name"
    if _selector_matches_agent(selector, notification):
        return "agent"
    return None


def _unavailable_id_matches(
    selector: str, plans: tuple[PendingPlan, ...]
) -> PendingPlanAmbiguity | PendingPlanMiss | None:
    """Match ID selectors against handled/stale plan notifications.

    Preserves the previous contract: an ID or unique ID prefix that names a
    no-longer-available proposal resolves to its terminal state (so callers
    report ``conflict_already_handled``/``gone_stale``) instead of
    ``not_found``.
    """
    from sase.main.plan_pending_diagnosis import (
        diagnose_located_plan_miss,
        miss_error_code,
    )

    pending_ids = {plan.notification.id for plan in plans}
    rest = [
        notification
        for notification in load_notifications(include_dismissed=True)
        if notification.action in PLAN_APPROVAL_ACTIONS
        and notification.id not in pending_ids
    ]
    exact = [n for n in rest if n.id == selector]
    matches = exact or [n for n in rest if selector and n.id.startswith(selector)]
    if not matches:
        return None
    if len(matches) > 1:
        return PendingPlanAmbiguity(selector=selector, candidates=())
    notification = matches[0]
    archive = _archive_path_for(notification)
    if archive is not None:
        miss = diagnose_located_plan_miss(selector, Path(archive))
        if miss_error_code(miss) in {"conflict_already_handled", "gone_stale"}:
            return miss
    state = action_state_for_notification(notification)
    if state == "already_handled":
        return PendingPlanMiss(
            selector=selector,
            header="action already handled",
            detail_lines=(),
            suggestions=(),
        )
    if state == "stale":
        return PendingPlanMiss(
            selector=selector,
            header="action is stale",
            detail_lines=(),
            suggestions=(),
        )
    return None


def _selector_resolves_to_path(selector: str, plan: PendingPlan) -> bool:
    candidate = Path(selector).expanduser()
    if not candidate.is_absolute():
        candidate = Path.cwd() / candidate
    resolved = candidate.resolve(strict=False)
    for raw in (plan.archive_path, plan.bundle_plan_path):
        if raw and Path(raw).expanduser().resolve(strict=False) == resolved:
            return True
    return False


def _selector_matches_agent(selector: str, notification: Notification) -> bool:
    """Match planner-agent spellings: ``0qw``, ``@0qw``, ``0qw--plan``."""
    text = selector.strip().removeprefix("@")
    if not text:
        return False
    lowered = text.lower()
    for key in ("agent_name", "agent_cl_name"):
        agent = (notification.action_data.get(key) or "").strip()
        if not agent:
            continue
        agent_lower = agent.lower()
        if lowered == agent_lower:
            return True
        for suffix in ("--plan", "--gate"):
            if (
                lowered == f"{agent_lower}{suffix}"
                or agent_lower == f"{lowered}{suffix}"
            ):
                return True
    return False


def _shard_prefixed_name(archive_path: str) -> str | None:
    parts = Path(archive_path).parts
    if len(parts) >= 2 and len(parts[-2]) == 6 and parts[-2].isdigit():
        return f"{parts[-2]}/{Path(archive_path).stem}"
    return None


def _with_matched_by(plan: PendingPlan, how: str) -> PendingPlan:
    return PendingPlan(
        notification=plan.notification,
        name=plan.name,
        display_name=plan.display_name,
        archive_path=plan.archive_path,
        bundle_plan_path=plan.bundle_plan_path,
        title=plan.title,
        tier=plan.tier,
        agent=plan.agent,
        age=plan.age,
        matched_by=how,
    )


def _archive_path_for(notification: Notification) -> str | None:
    from sase._plan_approval_artifacts import durable_plan_file_for_context

    context = PlanApprovalActionContext(
        id=notification.id,
        host_files=tuple(notification.files),
        host_action_data=dict(notification.action_data),
    )
    try:
        resolved = durable_plan_file_for_context(context)
    except Exception:
        return None
    return str(resolved) if resolved is not None else None


def _bundle_plan_path_for(notification: Notification) -> str | None:
    files = notification.files
    return files[0] if files else None


def _tier_for(notification: Notification, metadata_tier: str) -> str:
    tier = (notification.action_data.get("plan_tier") or "").strip().lower()
    if tier in {"tale", "epic"}:
        return tier
    if metadata_tier in {"tale", "epic"}:
        return metadata_tier
    return "epic" if notification.action == "EpicApproval" else "tale"


def _agent_for(notification: Notification) -> str:
    return (
        (notification.action_data.get("agent_name") or "").strip()
        or (notification.action_data.get("agent_cl_name") or "").strip()
        or "-"
    )


def ensure_plan_notification_available(notification: Notification) -> None:
    """Raise when *notification* is not an available plan approval action."""
    if notification.action not in PLAN_APPROVAL_ACTIONS:
        raise PlanApprovalActionError(
            "unsupported_action",
            notification.action or "non_action",
            "notification is not a plan approval",
        )

    state = action_state_for_notification(notification)
    if state == "available":
        return
    if state == "already_handled":
        raise PlanApprovalActionError(
            "conflict_already_handled", notification.id, "action already handled"
        )
    if state == "stale":
        raise PlanApprovalActionError("gone_stale", notification.id, "action is stale")
    raise PlanApprovalActionError(
        "invalid_request", notification.id, f"action is {state}"
    )


def plan_context_from_notification(
    notification: Notification,
) -> PlanApprovalActionContext:
    """Build the host-side action context for a resolved notification."""
    return PlanApprovalActionContext(
        id=notification.id,
        host_files=tuple(str(Path(path).expanduser()) for path in notification.files),
        host_action_data=dict(notification.action_data),
    )


__all__ = [
    "PendingPlan",
    "PendingPlanAmbiguity",
    "PendingPlanMatch",
    "PendingPlanMiss",
    "ensure_plan_notification_available",
    "pending_plans",
    "plan_context_from_notification",
    "resolve_pending_plan",
    "resolve_pending_plan_selector",
]
