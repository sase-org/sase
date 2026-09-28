"""Locked goal write transactions (epic sase-1bu, phases ledger-root/publish-sync).

Shared-mode writes retry a pending outbox, fetch before minting a new id,
append through the hidden clone under :func:`store_git_write_lock`,
recover crash leftovers first, commit only ``goals/``, and publish
synchronously through the existing managed sync worker. A failed publish
is never a failed write: the event is durable locally, the outbox records
the debt, and the outcome reports ``published=False``. Local mode appends
with no git.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from sase.goals.store import GoalLedger

logger = logging.getLogger(__name__)

GOALS_COMMIT_PREFIX = "chore(goals)"
GOALS_RECOVERY_MESSAGE = f"{GOALS_COMMIT_PREFIX}: recover uncommitted ledger files"

GoalWriteStatus = Literal["applied", "refused", "stale_basis"]


class GoalWriteError(RuntimeError):
    """A goal write transaction failed before reaching the ledger."""


@dataclass(frozen=True)
class GoalWriteOutcome:
    """Result of :func:`apply_goal_action`."""

    status: GoalWriteStatus
    goal_id: str | None
    code: str | None = None
    message: str | None = None
    events: tuple[dict[str, Any], ...] = ()
    states: tuple[dict[str, Any], ...] = ()
    committed: bool = False
    commit_message: str | None = None
    published: bool = False
    publish_error: str | None = None
    recovery_commit: str | None = None
    outbox_pending: bool = False
    outbox: dict[str, Any] | None = None
    offline_mint: bool = False
    push_attempts: int = 0


def default_goal_actor() -> dict[str, Any]:
    """Build the event actor from owner identity and agent discovery."""
    principal = "unknown.unknown"
    try:
        from sase.config._owner import get_agent_owner_identity

        owner = get_agent_owner_identity()
        if owner is not None:
            principal = f"{owner.username}.{owner.machine_name}"
    except Exception:  # noqa: BLE001 - actor building never fails a write.
        pass
    actor: dict[str, Any] = {"principal": principal, "kind": "human"}
    try:
        from sase.agent.identity import discover_agent_identity

        identity = discover_agent_identity()
        if identity is not None:
            actor = {
                "principal": principal,
                "kind": "agent",
                "agent": identity.name,
            }
    except Exception:  # noqa: BLE001 - actor building never fails a write.
        pass
    return actor


def apply_goal_action(
    ledger: GoalLedger,
    action: dict[str, Any],
    actor: dict[str, Any] | None = None,
    *,
    publish: bool = True,
    push_timeout_seconds: float | None = None,
) -> GoalWriteOutcome:
    """Append *action* to *ledger* and commit (then publish) the result."""
    from sase.core.goal_ledger_facade import goal_ledger_append, goal_ledger_init

    resolved_actor = dict(actor) if actor is not None else default_goal_actor()
    if ledger.mode == "local":
        ledger.root.mkdir(parents=True, exist_ok=True)
        goal_ledger_init(ledger.root)
        outcome = goal_ledger_append(
            ledger.root,
            {
                "action": dict(action),
                "actor": resolved_actor,
                "lock_path": str(ledger.lock_path),
            },
        )
        return _outcome_from_append(outcome)
    return _apply_shared(ledger, action, resolved_actor, publish, push_timeout_seconds)


def retry_pending_goals_publish(
    ledger: GoalLedger,
    *,
    push_timeout_seconds: float | None = None,
) -> dict[str, Any]:
    """Retry a pending outbox publish; return ``{retried, published, error}``."""
    from sase.core.paths import sase_projects_dir

    from sase.goals.outbox import (
        clear_goals_outbox,
        goals_outbox_pending,
        record_goals_publish_failure,
    )
    from sase.goals.sync_stats import record_goals_publish

    result: dict[str, Any] = {"retried": False, "published": False, "error": None}
    if ledger.mode != "shared" or ledger.hidden_clone is None:
        return result
    if not goals_outbox_pending(ledger.outbox_path):
        return result
    result["retried"] = True
    published, error, attempts = _publish_hidden_clone(ledger, push_timeout_seconds)
    result["published"] = published
    result["error"] = error
    stats_path = sase_projects_dir() / ledger.project / "goals-sync-stats.json"
    try:
        record_goals_publish(
            stats_path,
            push_attempts=attempts,
            rejected_after_max=bool(error) and "rejected after" in str(error),
        )
    except Exception:  # noqa: BLE001 - stats never fail a retry.
        pass
    try:
        if published:
            clear_goals_outbox(ledger.outbox_path)
        else:
            record_goals_publish_failure(ledger.outbox_path, error)
    except Exception:  # noqa: BLE001 - outbox bookkeeping never fails a retry.
        pass
    return result


def _is_new_action(action: dict[str, Any]) -> bool:
    raw = action.get("action", "")
    return isinstance(raw, str) and raw.lower() == "new"


def _fetch_before_mint(ledger: GoalLedger) -> bool:
    """Bounded integration before minting; return True when offline.

    Runs under the caller's store write lock via handoff so the fetch and
    the append that follows stay atomic. Fails open: any error means the
    mint proceeds against local state with ``offline_mint=True``.
    """
    from sase.sdd._git_contention import handoff_store_git_write_lock
    from sase.sdd._repository_transaction import integrate_sdd_repository

    assert ledger.hidden_clone is not None
    repo = ledger.hidden_clone
    try:
        beads_dir = repo / "beads"
        integration = integrate_sdd_repository(
            repo,
            beads_dir=beads_dir if beads_dir.exists() else None,
            op_prefix="goals.mint_fetch",
            lock_factory=handoff_store_git_write_lock,
        )
        return not integration.succeeded
    except Exception as exc:  # noqa: BLE001 - mint fetch fails open.
        logger.warning("goals fetch-before-mint for %s failed: %s", ledger.project, exc)
        return True


def _mint_new_goal_id(ledger: GoalLedger) -> str:
    """Mint an id after the fetch, retrying on local collision."""
    from sase.core.goal_ledger_facade import goal_mint_id

    for _ in range(10):
        candidate = goal_mint_id()
        if not (ledger.root / "items" / candidate).exists():
            return candidate
    return goal_mint_id()


def _apply_shared(
    ledger: GoalLedger,
    action: dict[str, Any],
    actor: dict[str, Any],
    publish: bool,
    push_timeout_seconds: float | None,
) -> GoalWriteOutcome:
    from sase.core.goal_ledger_facade import goal_ledger_append, goal_ledger_init
    from sase.sdd._git_contention import store_git_write_lock

    assert ledger.hidden_clone is not None
    repo = ledger.hidden_clone
    # Retry a pending outbox first so mutating writes drain publish debt.
    if publish:
        try:
            retry_pending_goals_publish(
                ledger, push_timeout_seconds=push_timeout_seconds
            )
        except Exception as exc:  # noqa: BLE001 - retry fails open.
            logger.warning("goals outbox retry for %s failed: %s", ledger.project, exc)
    with store_git_write_lock(
        repo, op="goals.write", mutates_worktree=True
    ) as acquired:
        if not acquired:
            raise GoalWriteError(
                f"goal write for {ledger.project} could not acquire the store "
                "write lock; no files were changed"
            )
        from sase.workspace_provider.ownership import authorize_store_mutation

        authorize_store_mutation(repo, mutation_origin="machine")
        recovery = _recover_uncommitted_goals(repo)
        goal_ledger_init(ledger.root)
        offline_mint = False
        request: dict[str, Any] = {
            "action": dict(action),
            "actor": dict(actor),
            "lock_path": str(ledger.lock_path),
        }
        if _is_new_action(action):
            offline_mint = _fetch_before_mint(ledger)
            request["new_goal_id"] = _mint_new_goal_id(ledger)
        append_outcome = goal_ledger_append(ledger.root, request)
        outcome = _outcome_from_append(
            append_outcome, recovery_commit=recovery, offline_mint=offline_mint
        )
        if outcome.status != "applied":
            return outcome
        message = _commit_message(action, outcome)
        committed = _commit_goal_paths(repo, message)
        outcome = GoalWriteOutcome(
            status=outcome.status,
            goal_id=outcome.goal_id,
            code=outcome.code,
            message=outcome.message,
            events=outcome.events,
            states=outcome.states,
            committed=committed,
            commit_message=message if committed else None,
            published=False,
            publish_error=None,
            recovery_commit=recovery,
            offline_mint=offline_mint,
        )
    if publish:
        published, error, attempts = _publish_hidden_clone(ledger, push_timeout_seconds)
        outcome = _record_publish_result(ledger, outcome, published, error, attempts)
    return outcome


def _outcome_from_append(
    append_outcome: dict[str, Any],
    recovery_commit: str | None = None,
    offline_mint: bool = False,
) -> GoalWriteOutcome:
    status = str(append_outcome.get("status", "refused"))
    if status not in ("applied", "refused", "stale_basis"):
        status = "refused"
    events = tuple(append_outcome.get("events", ()))
    states = tuple(append_outcome.get("states", ()))
    goal_id: str | None = None
    if states and isinstance(states[0], dict):
        goal_id = states[0].get("id")
    if goal_id is None and events and isinstance(events[0], dict):
        goal_id = events[0].get("goal_id")
    code = append_outcome.get("code")
    message = append_outcome.get("message")
    return GoalWriteOutcome(
        status=status,  # type: ignore[arg-type]
        goal_id=goal_id,
        code=str(code) if code is not None else None,
        message=str(message) if message is not None else None,
        events=events,
        states=states,
        recovery_commit=recovery_commit,
        offline_mint=offline_mint,
    )


def _record_publish_result(
    ledger: GoalLedger,
    outcome: GoalWriteOutcome,
    published: bool,
    error: str | None,
    push_attempts: int,
) -> GoalWriteOutcome:
    """Record outbox + contention stats; attach them to a new outcome."""
    from sase.core.paths import sase_projects_dir

    from sase.goals.outbox import (
        clear_goals_outbox,
        read_goals_outbox,
        record_goals_publish_failure,
    )
    from sase.goals.sync_stats import record_goals_publish

    stats_path = sase_projects_dir() / ledger.project / "goals-sync-stats.json"
    rejected = bool(error) and "rejected after" in str(error)
    try:
        record_goals_publish(
            stats_path, push_attempts=push_attempts, rejected_after_max=rejected
        )
    except Exception:  # noqa: BLE001 - stats never fail a write.
        pass
    outbox: dict[str, Any] | None
    if published:
        outbox = clear_goals_outbox(ledger.outbox_path)
    elif outcome.committed:
        outbox = record_goals_publish_failure(ledger.outbox_path, error)
    else:
        outbox = read_goals_outbox(ledger.outbox_path)
    return GoalWriteOutcome(
        status=outcome.status,
        goal_id=outcome.goal_id,
        code=outcome.code,
        message=outcome.message,
        events=outcome.events,
        states=outcome.states,
        committed=outcome.committed,
        commit_message=outcome.commit_message,
        published=published,
        publish_error=error,
        recovery_commit=outcome.recovery_commit,
        outbox_pending=bool(outbox.get("pending")) if outbox else False,
        outbox=outbox,
        offline_mint=outcome.offline_mint,
        push_attempts=push_attempts,
    )


def _action_verb(action: dict[str, Any]) -> str:
    verb = action.get("action", "update")
    return str(verb) if verb else "update"


def _tagged_goals_message(message: str) -> str:
    """Stamp the goal auto-commit ``TYPE`` tag (plus runtime provenance)."""
    from sase.workflows.commit.runtime_tags import apply_auto_commit_tags_with_runtime

    return apply_auto_commit_tags_with_runtime(message, "goals")


def _commit_message(action: dict[str, Any], outcome: GoalWriteOutcome) -> str:
    goal = outcome.goal_id or "unknown"
    return _tagged_goals_message(
        f"{GOALS_COMMIT_PREFIX}: {_action_verb(action)} goal {goal}"
    )


def _recover_uncommitted_goals(repo: Path) -> str | None:
    """Commit crash-leftover ``goals/`` files; return the message or None."""
    from sase.sdd._git import run_sdd_git

    status = run_sdd_git(
        ["status", "--porcelain", "--", "goals"],
        cwd=repo,
        check=False,
        capture_output=True,
        text=True,
        op="goals.recover_status",
    )
    if status.returncode != 0 or not status.stdout.strip():
        return None
    tagged = _tagged_goals_message(GOALS_RECOVERY_MESSAGE)
    if _commit_goal_paths(repo, tagged):
        logger.warning("recovered uncommitted goal ledger files in %s", repo)
        return tagged
    return None


def commit_goal_paths(repo: Path, message: str) -> bool:
    """Stage exactly ``goals/`` and commit; return True on a new commit.

    The caller holds the store write lock (see ``sase goal doctor``).
    """
    return _commit_goal_paths(repo, message)


def _commit_goal_paths(repo: Path, message: str) -> bool:
    """Stage exactly ``goals/`` and commit; return True on a new commit."""
    from sase.sdd._git import run_sdd_git
    from sase.sdd._git_contention import run_sdd_git_write

    run_sdd_git_write(
        ["add", "-A", "--", "goals"],
        cwd=repo,
        check=True,
        capture_output=True,
        op="goals.add",
    )
    diff = run_sdd_git(
        ["diff", "--cached", "--quiet", "--", "goals"],
        cwd=repo,
        capture_output=True,
        check=False,
        op="goals.diff_cached",
    )
    if diff.returncode == 0:
        return False
    run_sdd_git_write(
        ["commit", "-m", message],
        cwd=repo,
        check=True,
        capture_output=True,
        op="goals.commit",
    )
    return True


def _publish_hidden_clone(
    ledger: GoalLedger, push_timeout_seconds: float | None
) -> tuple[bool, str | None, int]:
    """Synchronously publish the hidden clone; never raises.

    Returns ``(published, error, push_attempts)`` and reconciles live
    markers after the integration, fails-open, before reporting.
    """
    from sase.bead.sync import MUTATION_PUBLICATION_WORKER_LOCK_WAIT_SECONDS
    from sase.bead.sync import push_bead_work_launch
    from sase.goals.config import goals_push_timeout_seconds

    assert ledger.hidden_clone is not None
    timeout = (
        float(push_timeout_seconds)
        if push_timeout_seconds is not None
        else goals_push_timeout_seconds()
    )
    deadline = time.monotonic() + max(0.0, timeout)
    try:
        outcome = push_bead_work_launch(
            ledger.hidden_clone,
            worker_lock_wait=min(
                MUTATION_PUBLICATION_WORKER_LOCK_WAIT_SECONDS, max(0.0, timeout)
            ),
            deadline=deadline,
        )
    except Exception as exc:  # noqa: BLE001 - publish failure is not a write failure.
        logger.warning("goal publish for %s failed: %s", ledger.project, exc)
        return False, str(exc), 0
    attempts = int(getattr(outcome, "push_attempts", 0) or 0)
    if outcome.pushed:
        _reconcile_and_repush(ledger, deadline)
        return True, None, attempts
    if getattr(outcome, "skipped_no_remote", False):
        return False, "hidden clone has no push remote", attempts
    if getattr(outcome, "skipped_locked", False):
        return False, "sync worker busy", attempts
    error = getattr(outcome, "error", None)
    return False, str(error) if error else "push did not complete", attempts


def _reconcile_and_repush(ledger: GoalLedger, deadline: float | None) -> None:
    """Reconcile markers after a publish; push again when it commits."""
    try:
        from sase.goals.reconcile import reconcile_goals_after_integration

        reconcile = reconcile_goals_after_integration(ledger)
        if not reconcile.get("commit"):
            return
        from sase.bead.sync import push_bead_work_launch

        push_bead_work_launch(
            ledger.hidden_clone,  # type: ignore[arg-type]
            worker_lock_wait=0.0,
            deadline=deadline,
        )
    except Exception as exc:  # noqa: BLE001 - reconcile fails open.
        logger.warning(
            "goals post-publish reconcile for %s failed: %s", ledger.project, exc
        )
