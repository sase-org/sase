"""Settle the trigger agent and own the notification for an automatic drain.

``handle_possible_usage_limit`` submits ``sase agent drain`` as a durable proc
while the agent whose failure caused the disable is still mid-teardown. This
module is the seam ``sase.ops.commands.agent._run_drain`` uses to bridge that
gap: wait a bounded time for the trigger agent to finish, then send the one
enriched usage-limit notification the drain proc owns, built from the same
JSON envelope ``sase agent drain --json`` reports.
"""

from __future__ import annotations

from collections.abc import Mapping
import logging
from typing import Any

logger = logging.getLogger(__name__)

_SETTLE_TIMEOUT_SECONDS = 60.0


def settle_drain_trigger_agent(
    name: str | None, *, timeout_seconds: float = _SETTLE_TIMEOUT_SECONDS
) -> None:
    """Best-effort wait for *name* to reach a terminal state before draining.

    Without this, drain selection would see the just-failed trigger agent as
    still live and kill it mid-teardown instead of restarting it from its
    natural FAILED state. Never raises; a timeout is not an error and
    planning proceeds with whatever state the agent is in.
    """
    if not name:
        return
    from sase.agent.wait_watch import (
        WaitTargetResolutionError,
        WaitWatchConfig,
        resolve_wait_targets,
        wait_scan_options,
        watch_wait_targets,
    )
    from sase.core.agent_scan_facade import scan_agent_artifacts
    from sase.core.paths import sase_projects_dir

    try:
        root = sase_projects_dir()
        options = wait_scan_options()

        def provider() -> Any:
            return scan_agent_artifacts(root, options)

        targets = resolve_wait_targets([name], provider())
        if not targets:
            return
        config = WaitWatchConfig(targets=targets, timeout_seconds=timeout_seconds)
        for tick in watch_wait_targets(config, provider):
            if tick.settled:
                break
    except WaitTargetResolutionError:
        return
    except Exception:
        logger.warning(
            "failed to settle drain trigger agent %r before draining",
            name,
            exc_info=True,
        )


def send_usage_limit_drain_notification(
    trigger: Mapping[str, Any], result: Any
) -> None:
    """Send the one enriched usage-limit notification a drain proc owns.

    *trigger* is the operation payload ``handle_possible_usage_limit``
    submitted (matched pattern, disable window, trigger agent/model).
    *result* is the ``_AgentDrainCommandResult`` ``run_agents_drain``
    produced, or ``None`` when the drain raised before finishing. Never
    raises: a notification bug must never mask a drain that already ran.
    """
    try:
        from sase.agents._drain_render import usage_limit_drain_report_notes
        from sase.llm_provider.usage_limit_config import UsageLimitDetection
        from sase.notifications.senders import notify_provider_usage_limit_disabled

        detection = UsageLimitDetection(
            provider=str(trigger.get("provider") or ""),
            matched_pattern=str(trigger.get("matched_pattern") or ""),
            message=str(trigger.get("matched_pattern") or ""),
            raw_message=str(trigger.get("raw_message") or ""),
            disable_seconds=float(trigger.get("disable_seconds") or 0.0),
            expires_at=_optional_float(trigger.get("expires_at")),
            reset_hint=None,
            used_reset_hint=bool(trigger.get("used_reset_hint", False)),
        )
        payload = getattr(result, "payload", None)
        notify_provider_usage_limit_disabled(
            detection,
            agent_name=_optional_str(trigger.get("trigger_agent")),
            model=_optional_str(trigger.get("trigger_model")),
            drain_notes=usage_limit_drain_report_notes(payload),
        )
    except Exception:
        logger.warning("usage-limit drain notification failed", exc_info=True)


def _optional_str(value: Any) -> str | None:
    return value if isinstance(value, str) and value else None


def _optional_float(value: Any) -> float | None:
    return float(value) if isinstance(value, int | float) else None


__all__ = [
    "send_usage_limit_drain_notification",
    "settle_drain_trigger_agent",
]
