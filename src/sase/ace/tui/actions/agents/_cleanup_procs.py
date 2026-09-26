"""Tracked proc helpers for TUI agent kill/dismiss persistence."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Literal
from uuid import uuid4

from ..proc_actions import TrackedProcCompletion

CleanupSeverity = Literal["warning", "error"]


@dataclass(frozen=True)
class _CleanupProcOutcome:
    """UI-thread effects to apply after a cleanup proc completes."""

    message: str
    severity: CleanupSeverity | None = None
    notify: bool = False
    refresh_notifications: bool = False
    schedule_agents_refresh_source: str | None = None

    @property
    def success(self) -> bool:
        """Return whether this outcome should be recorded as proc success."""
        return self.severity != "error"


class CleanupProcMixin:
    """Mixin that routes kill/dismiss persistence through the central proc queue."""

    def _submit_cleanup_proc(
        self,
        *,
        proc_type: str,
        display_name: str,
        cl_name: str,
        project_file: str,
        payload: dict[str, object] | None = None,
        on_settled: Callable[[], None] | None = None,
    ) -> bool:
        """Submit a durable cleanup persist proc and return whether it was accepted."""
        from ..agent_durable import submit_agent_cleanup
        from ..cleanup_payload import json_identities

        request_payload = dict(payload or {})
        request_payload.setdefault("action", proc_type)
        added = request_payload.get("added_identities")
        if isinstance(added, (set, list, tuple)) and added:
            first = next(iter(added))
            if isinstance(first, tuple):
                request_payload["added_identities"] = json_identities(added)
        identity = str(request_payload.get("identity") or f"{proc_type}:{uuid4().hex}")
        submitted = submit_agent_cleanup(
            self,
            proc_type=proc_type,
            identity=identity,
            payload=request_payload,
            cl_name=cl_name,
            project_file=project_file,
            display_name=display_name,
            on_complete=self._on_cleanup_proc_complete,
            on_settled=on_settled,
        )
        return submitted

    def _on_cleanup_proc_complete(
        self,
        completion: TrackedProcCompletion[_CleanupProcOutcome],
    ) -> None:
        """Apply cleanup-specific completion effects on the UI thread."""
        self._resurface_failed_cleanup_members(completion)
        outcome = _cleanup_outcome_from_completion(completion)
        if outcome is None:
            if not completion.success:
                self.notify(  # type: ignore[attr-defined]
                    f"Cleanup task failed: {completion.message}",
                    severity="error",
                )
            return

        if outcome.notify and outcome.message:
            self.notify(  # type: ignore[attr-defined]
                outcome.message,
                severity=outcome.severity or "information",
            )

        if outcome.schedule_agents_refresh_source is not None:
            self._schedule_agents_async_refresh(  # type: ignore[attr-defined]
                source=outcome.schedule_agents_refresh_source
            )

        if outcome.refresh_notifications:
            # Off-thread refresh: the notifications file is read in a worker
            # thread and the indicator update lands back on the UI thread.
            schedule_refresh = getattr(
                self,
                "_schedule_notification_snapshot_refresh",
                None,
            )
            if callable(schedule_refresh):
                schedule_refresh()
            else:
                # Narrow mixin users/tests may omit the notification-provider
                # coalescer. They still use the same pump-free execution
                # boundary rather than falling back to ``call_later(async)``.
                from ...util.pump_tasks import spawn_pump_free_task

                spawn_pump_free_task(
                    self,
                    self._refresh_notification_count_async(),  # type: ignore[attr-defined]
                    name="sase-cleanup-notification-count-refresh",
                    registry_attr="_pump_free_async_tasks",
                )

    def _resurface_failed_cleanup_members(self, completion: object) -> None:
        """Clear tombstones and dismissal state for resurfaced identities.

        The durable proc reports member stops/cancels that never settled via
        ``resurface_identities``; their rows must come back on the next
        refresh instead of staying tombstoned.
        """
        identities = _resurface_identities_from_completion(completion)
        if not identities:
            return
        clear_removals = getattr(self, "clear_explicit_removals", None)
        if callable(clear_removals):
            clear_removals(identities)
        dismissed = getattr(self, "_dismissed_agents", None)
        if isinstance(dismissed, set):
            dismissed.difference_update(identities)
        dismissed_shells = getattr(self, "_dismissed_proc_shells", None)
        if isinstance(dismissed_shells, set):
            from sase.core.agent_types import AgentType

            dismissed_shells.difference_update(
                {
                    suffix
                    for agent_type, _cl_name, suffix in identities
                    if agent_type == AgentType.NAMED_PROC and isinstance(suffix, str)
                }
            )


def _resurface_identities_from_completion(
    completion: object,
) -> set[tuple[Any, ...]]:
    """Return member identities the durable proc asked to resurface."""
    payload = getattr(completion, "payload", None)
    if not isinstance(payload, dict):
        return set()
    raw = payload.get("resurface_identities")
    if not isinstance(raw, list):
        return set()
    from ..cleanup_payload import identities_from_json

    try:
        return {tuple(identity) for identity in identities_from_json(raw)}
    except ValueError:
        return set()


def _cleanup_outcome_from_completion(
    completion: TrackedProcCompletion[_CleanupProcOutcome],
) -> _CleanupProcOutcome | None:
    payload = completion.payload
    if isinstance(payload, _CleanupProcOutcome):
        return payload
    if not isinstance(payload, dict):
        return None
    severity = payload.get("severity")
    return _CleanupProcOutcome(
        message=str(payload.get("message") or completion.message),
        severity=severity if severity in {"warning", "error"} else None,
        notify=bool(payload.get("notify", False)),
        refresh_notifications=bool(payload.get("refresh_notifications", False)),
        schedule_agents_refresh_source=(
            str(payload["schedule_agents_refresh_source"])
            if payload.get("schedule_agents_refresh_source")
            else None
        ),
    )


__all__ = [
    "CleanupProcMixin",
]
