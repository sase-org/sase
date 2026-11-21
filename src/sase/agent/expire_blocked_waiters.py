"""Expire waiters named by a wait_checks root-blocker notice.

The TUI ``ExpireWaiters`` action calls this operation after confirmation.
Each still-parked waiter is stopped through
:func:`sase.agent.running.kill_located_agent`, the same user-kill path a
manual cancel of a waiting agent uses. Waiters that already started or
settled are skipped. Nothing here launches a waiter or expires one without
an explicit call.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from sase.agent.names import NamedAgent
from sase.agent.running import KillResult, kill_located_agent
from sase.core.wait_dependency_resolution._artifact_state import (
    done_outcome,
    waiting_marker_crossed_dependency_barrier,
)
from sase.core.wait_dependency_resolution._json_io import read_json_dict
from sase.notifications.models import Notification
from sase.notifications.store import mark_dismissed
from sase.scripts._chop_wait_checks_root_notice import (
    EXPIRE_WAITERS_ACTION as EXPIRE_WAITERS_ACTION,
    waiters_from_root_notice,
)
from sase.scripts._chop_wait_checks_roots import RootWaiter

EXPIRE_WAITERS_SOURCE = "expire_blocked_waiters"

WaiterExpireStatus = Literal[
    "expired",
    "skipped_started",
    "skipped_settled",
    "skipped_missing",
    "failed",
]


@dataclass(frozen=True)
class WaiterExpireResult:
    """Per-waiter outcome of one expire pass."""

    artifact_dir: str
    name: str
    status: WaiterExpireStatus
    message: str


@dataclass(frozen=True)
class ExpireBlockedWaitersResult:
    """Aggregate result of expiring every waiter a root notice names."""

    results: tuple[WaiterExpireResult, ...]
    notice_settled: bool

    @property
    def expired_count(self) -> int:
        return sum(1 for result in self.results if result.status == "expired")

    @property
    def skipped_count(self) -> int:
        return sum(1 for result in self.results if result.status.startswith("skipped_"))

    @property
    def failed_count(self) -> int:
        return sum(1 for result in self.results if result.status == "failed")


def expire_blocked_waiters(notification: Notification) -> ExpireBlockedWaitersResult:
    """Expire still-parked waiters named by *notification* and settle the row.

    Returns per-waiter results. The notice is dismissed only when no waiter
    failed; skipped waiters (already started or settled) still settle the
    row because they are no longer parked behind the blocker.
    """
    reason = _blocker_reason(notification)
    results = tuple(
        _expire_one_waiter(waiter, reason=reason)
        for waiter in waiters_from_root_notice(notification)
    )
    if not results and notification.action_data.get("waiter_count", "0") != "0":
        return ExpireBlockedWaitersResult(
            results=(
                WaiterExpireResult(
                    artifact_dir="",
                    name="waiter list",
                    status="failed",
                    message="Notification waiter payload is missing or invalid",
                ),
            ),
            notice_settled=False,
        )
    notice_settled = False
    if results and not any(result.status == "failed" for result in results):
        notice_settled = mark_dismissed(notification.id)
    elif not results:
        notice_settled = mark_dismissed(notification.id)
    return ExpireBlockedWaitersResult(results=results, notice_settled=notice_settled)


def expire_blocked_waiters_summary(result: ExpireBlockedWaitersResult) -> str:
    """Return a one-line TUI/log summary of *result*."""
    parts = [f"Expired {result.expired_count} waiter(s)"]
    if result.skipped_count:
        parts.append(f"skipped {result.skipped_count}")
    if result.failed_count:
        parts.append(f"failed {result.failed_count}")
    if result.notice_settled:
        parts.append("notice settled")
    return "; ".join(parts)


def _expire_one_waiter(waiter: RootWaiter, *, reason: str) -> WaiterExpireResult:
    artifact_dir = Path(waiter.artifact_dir)
    skip = _skip_status(artifact_dir)
    if skip is not None:
        status, message = skip
        return WaiterExpireResult(
            artifact_dir=waiter.artifact_dir,
            name=waiter.name,
            status=status,
            message=message,
        )
    kill_result = kill_located_agent(
        NamedAgent(
            name=waiter.name,
            artifacts_dir=waiter.artifact_dir,
            is_done=False,
            outcome=None,
        ),
        reason=reason,
        source=EXPIRE_WAITERS_SOURCE,
    )
    return _result_from_kill(waiter, kill_result)


def _skip_status(artifact_dir: Path) -> tuple[WaiterExpireStatus, str] | None:
    """Return a skip status when this waiter must not be killed."""
    if not artifact_dir.is_dir():
        return "skipped_missing", "artifact directory is gone"
    if done_outcome(artifact_dir) is not None:
        return "skipped_settled", "waiter already settled"
    meta = read_json_dict(artifact_dir / "agent_meta.json") or {}
    if waiting_marker_crossed_dependency_barrier(artifact_dir, meta):
        return "skipped_started", "waiter already started"
    waiting = read_json_dict(artifact_dir / "waiting.json")
    if waiting is None:
        if (artifact_dir / "running.json").exists() or meta.get("run_started_at"):
            return "skipped_started", "waiter already started"
        return "skipped_settled", "waiter is no longer parked"
    if waiting.get("cancelled_by_hijack") is True:
        return "skipped_settled", "waiter already cancelled"
    return None


def _result_from_kill(
    waiter: RootWaiter, kill_result: KillResult
) -> WaiterExpireResult:
    if kill_result.success:
        return WaiterExpireResult(
            artifact_dir=waiter.artifact_dir,
            name=waiter.name,
            status="expired",
            message=kill_result.message,
        )
    if kill_result.status == "already_completed":
        return WaiterExpireResult(
            artifact_dir=waiter.artifact_dir,
            name=waiter.name,
            status="skipped_settled",
            message=kill_result.message,
        )
    return WaiterExpireResult(
        artifact_dir=waiter.artifact_dir,
        name=waiter.name,
        status="failed",
        message=kill_result.message,
    )


def _blocker_reason(notification: Notification) -> str:
    data = notification.action_data
    name = (
        data.get("blocker_name") or data.get("blocker_dependency") or "failed blocker"
    )
    outcome = data.get("blocker_outcome") or "unknown"
    artifact_dir = data.get("blocker_artifact_dir") or ""
    return f"expired: blocked on {name} ({outcome}) {artifact_dir}".strip()


__all__ = [
    "EXPIRE_WAITERS_ACTION",
    "EXPIRE_WAITERS_SOURCE",
    "ExpireBlockedWaitersResult",
    "WaiterExpireResult",
    "expire_blocked_waiters",
    "expire_blocked_waiters_summary",
]
