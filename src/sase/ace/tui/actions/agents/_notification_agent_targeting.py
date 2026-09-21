"""Agent roster and row-targeting helpers for notification refresh."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from inspect import Parameter, getattr_static, signature
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

if TYPE_CHECKING:
    from sase.notifications import Notification

    from ...models import Agent


TabName = Literal["artifacts", "agents", "services"]


def loaded_real_agent_roster(owner: Any) -> tuple[Agent, ...]:
    """Return the complete loaded display-eligible roster without clan rows.

    Notification targeting must resolve against every loaded agent, not
    just the currently visible/folded/filtered ``_agents`` projection, so
    a completion for a folded or search-hidden row still resolves to an
    exact artifact-delta refresh instead of falling back to a broad load.
    """
    roster: Iterable[Agent] = (
        getattr(owner, "_agents_with_children", None)
        or getattr(owner, "_agents", ())
        or ()
    )
    return tuple(agent for agent in roster if not agent.is_clan_container)


def callable_accepts_kwarg(callback: Callable[..., object], name: str) -> bool:
    try:
        params = signature(callback).parameters.values()
    except (TypeError, ValueError):
        return False
    return any(p.kind == Parameter.VAR_KEYWORD or p.name == name for p in params)


def call_schedule_agents_refresh(app: Any) -> None:
    if getattr_static(app, "request_agents_refresh", None) is not None:
        request_refresh = getattr(app, "request_agents_refresh", None)
        if callable(request_refresh):
            request_refresh("notification", latest_only=True)
            return

    schedule_refresh = getattr(app, "_schedule_agents_async_refresh", None)
    if not callable(schedule_refresh):
        return
    if callable_accepts_kwarg(schedule_refresh, "source"):
        schedule_refresh(source="notification")
    else:
        schedule_refresh()


def agent_artifact_dir(agent: Any) -> Path | None:
    get_artifacts_dir = getattr(agent, "get_artifacts_dir", None)
    if not callable(get_artifacts_dir):
        return None
    artifacts_dir = get_artifacts_dir()
    if not isinstance(artifacts_dir, str) or not artifacts_dir:
        return None
    return Path(artifacts_dir)


def resolve_notification_agent(
    app: Any,
    notification: Notification | None,
) -> Agent | None:
    if notification is None:
        return None
    try:
        from ._notification_navigation import find_agent_for_notification

        return find_agent_for_notification(app, notification)
    except Exception:
        return None


def refresh_notification_agent_from_cache(
    app: Any,
    *,
    agent: Agent | None = None,
    notification: Notification | None = None,
) -> bool:
    """Refresh notification-driven row state without forcing disk I/O."""
    if agent is None:
        agent = resolve_notification_agent(app, notification)
    if agent is None:
        return False

    agents_with_children = getattr(app, "_agents_with_children", None)
    refilter = getattr(app, "_refilter_agents", None)
    if (
        callable(refilter)
        and isinstance(agents_with_children, list)
        and agents_with_children
    ):
        refilter()
        return True

    try_patch = None
    if getattr_static(app, "_try_patch_agent_row", None) is not None:
        try_patch = getattr(app, "_try_patch_agent_row", None)
    if callable(try_patch):
        try:
            return bool(try_patch(agent))
        except Exception:
            return False
    return False
