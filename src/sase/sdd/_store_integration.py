"""Remote integration and recovery handling for workspace SDD clones."""

from __future__ import annotations

from collections.abc import Callable
import logging
from pathlib import Path
import time
from typing import TYPE_CHECKING

from sase.sdd._store_types import SddMaterializationError

if TYPE_CHECKING:
    from sase.sdd._repository_recovery_markers import FailedIntegrationCooldown

_logger = logging.getLogger(__name__)


def pull_sdd_clone(
    workspace_sdd: Path,
    *,
    strict: bool = False,
    fresh: bool = False,
    clock: Callable[[], float] | None = None,
) -> bool:
    from sase.sdd._repository_recovery_git import machine_recovery_cooldown_seconds
    from sase.sdd._repository_recovery_markers import (
        admit_failed_integration_cooldown,
        clear_failed_integration_marker,
        record_failed_integration_marker,
    )
    from sase.sdd._repository_transaction import SddIntegrationStatus

    cooldown_seconds = machine_recovery_cooldown_seconds()
    cooldown = None
    if not _has_unpushed_bead_commits(workspace_sdd):
        cooldown = admit_failed_integration_cooldown(
            workspace_sdd,
            cooldown_seconds=cooldown_seconds,
            clock=clock,
        )
    if cooldown is not None:
        _log_failed_integration_cooldown(
            workspace_sdd,
            cooldown,
            cooldown_seconds=cooldown_seconds,
            clock=clock,
        )
        return False

    from sase.sdd._integration_marker import (
        bead_refresh_mode,
        integration_is_fresh,
    )

    if (
        not fresh
        and bead_refresh_mode() != "blocking"
        and integration_is_fresh(workspace_sdd)
    ):
        return True

    from sase.sdd._repository_recovery import (
        admit_recovery_notice,
        recovery_failure_signature,
    )
    from sase.sdd._repository_transaction import (
        integrate_machine_managed_sdd_repository,
    )

    outcome = integrate_machine_managed_sdd_repository(
        workspace_sdd,
        beads_dir=(workspace_sdd / "beads"),
        op_prefix="sdd.clone",
    )
    if outcome.succeeded:
        clear_failed_integration_marker(workspace_sdd)
        if (
            outcome.status is SddIntegrationStatus.RECOVERED
            and outcome.recovery_ref is not None
        ):
            _logger.warning(
                "Recovered workspace SDD clone %s; retained local state at %s",
                workspace_sdd,
                outcome.recovery_ref,
            )
        return True
    if _records_failed_integration_cooldown(outcome):
        record_failed_integration_marker(workspace_sdd, outcome, clock=clock)
    if outcome.status is SddIntegrationStatus.RECOVERY_COOLDOWN:
        return False

    detail = outcome.error or f"SDD integration ended with {outcome.status.value}"
    signature = recovery_failure_signature(workspace_sdd, outcome)
    if admit_recovery_notice(workspace_sdd, signature):
        _logger.warning(
            "Failed to pull workspace SDD clone %s: %s",
            workspace_sdd,
            detail,
        )
    if outcome.status in {
        SddIntegrationStatus.RECOVERY_FAILED,
        SddIntegrationStatus.UNRECOVERABLE,
    } and admit_recovery_notice(workspace_sdd, signature, report=True):
        _append_recovery_error(
            workspace_sdd,
            detail=detail,
            signature=signature,
            recovery_ref=outcome.recovery_ref,
        )

    if outcome.status is SddIntegrationStatus.UNRECOVERABLE:
        from sase.sdd._repository_transaction import SddRepositoryHealthError

        if strict:
            raise SddRepositoryHealthError(detail)
        return False
    if strict and outcome.status not in {
        SddIntegrationStatus.REMOTE_UNAVAILABLE,
    }:
        raise SddMaterializationError(detail)
    return False


def _has_unpushed_bead_commits(workspace_sdd: Path) -> bool:
    """Keep unpublished bead history out of failed-integration cooldown."""
    try:
        from sase.bead.sync import unpushed_bead_commit_count

        return (
            unpushed_bead_commit_count(
                workspace_sdd,
                workspace_sdd / "beads",
            )
            > 0
        )
    except Exception:
        # Cooldown is only an optimization. If the safety probe cannot tell,
        # attempt integration instead of parking potentially unpublished work.
        return True


def _records_failed_integration_cooldown(outcome: object) -> bool:
    from sase.sdd._repository_transaction import (
        SddIntegrationOutcome,
        SddIntegrationStatus,
    )

    return (
        isinstance(outcome, SddIntegrationOutcome)
        and outcome.upstream_present
        and outcome.status
        in {
            SddIntegrationStatus.ABORTED_UNSUPPORTED_CONFLICTS,
            SddIntegrationStatus.RECOVERY_COOLDOWN,
            SddIntegrationStatus.RECOVERY_FAILED,
            SddIntegrationStatus.UNRECOVERABLE,
        }
    )


def _log_failed_integration_cooldown(
    workspace_sdd: Path,
    cooldown: FailedIntegrationCooldown,
    *,
    cooldown_seconds: float,
    clock: Callable[[], float] | None = None,
) -> None:
    try:
        from sase.logs import log_tui_git_operation

        log_tui_git_operation(
            {
                "ts": (clock or time.time)(),
                "event": "sdd_git_operation",
                "operation": "sdd.clone.integration_cooldown",
                "status": "suppressed",
                "duration_ms": 0.0,
                "returncode": None,
                "cwd": str(workspace_sdd),
                "cmd": [
                    "git",
                    "fetch/rebase",
                    "[suppressed by failed-integration cooldown]",
                ],
                "stdout_preview": (
                    "suppressed repeated SDD integration attempt "
                    f"({cooldown.suppressed_count} suppressed since failure)"
                ),
                "stderr_preview": _preview_text(cooldown.error),
                "cooldown_seconds": cooldown_seconds,
                "failed_status": cooldown.status,
                "failure_signature": cooldown.signature,
                "failure_timestamp": cooldown.timestamp,
                "suppressed_count": cooldown.suppressed_count,
            }
        )
    except Exception:
        _logger.debug(
            "Failed to log SDD integration cooldown for %s",
            workspace_sdd,
            exc_info=True,
        )


def _preview_text(value: str | None, limit: int = 500) -> str | None:
    if value is None:
        return None
    text = value.strip()
    return text[:limit] if text else None


def _append_recovery_error(
    workspace_sdd: Path,
    *,
    detail: str,
    signature: str,
    recovery_ref: str | None,
) -> None:
    """Best-effort bridge from terminal clone recovery into axe digests."""
    try:
        from sase.axe.state import append_error, get_timestamp

        append_error(
            {
                "timestamp": get_timestamp(),
                "lumberjack": "sdd-sidecar",
                "job": "workspace_sdd_clone_recovery",
                "error": detail,
                "traceback": "[repository recovery outcome; no traceback]",
                "clone_path": str(workspace_sdd.expanduser().resolve()),
                "failure_signature": signature,
                "recovery_ref": recovery_ref,
            }
        )
    except Exception:  # noqa: BLE001 - reporting must not replace the Git outcome
        _logger.debug(
            "Failed to append workspace SDD recovery error for %s",
            workspace_sdd,
            exc_info=True,
        )
