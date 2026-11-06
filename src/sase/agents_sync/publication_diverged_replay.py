"""Bounded recovery and parking for conflicted publication rebases."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
import json
import logging
from pathlib import Path
import subprocess
import time
from uuid import uuid4

from sase.agents_sync.git import GitRunner
from sase.agents_sync.git_sync_ops import abort_agents_rebase, pull_agents_rebase
from sase.agents_sync.io import atomic_write_json
from sase.core.agent_publication_recovery import (
    PUBLICATION_REBASE_ACTION_RESOLVE_UPSTREAM,
    decide_publication_rebase_conflict,
)
from sase.core.paths import sase_projects_dir, validate_sase_project_name
from sase.sdd._repository_recovery_git import recovery_ref, update_and_verify_ref

log = logging.getLogger(__name__)

PUBLICATION_REBASE_FAILURE_STAGE = "diverged_replay"
PUBLICATION_REPLAY_COOLDOWN_SECONDS = 60 * 60
_MARKER_FILENAME = "diverged-replay.json"
_MARKER_SCHEMA_VERSION = 1
_MAX_CONFLICT_RESOLUTIONS = 25


@dataclass(frozen=True, slots=True)
class _PublicationRebaseResult:
    """One pull outcome, including whether the failure needs manual recovery."""

    process: subprocess.CompletedProcess[str]
    failure_stage: str | None = None
    conflict_paths: tuple[str, ...] = ()
    healed: bool = False


@dataclass(frozen=True, slots=True)
class _DivergedReplayMarker:
    """Persisted evidence identifying one publication replay that must wait."""

    project_key: str
    head: str
    upstream: str
    paths: tuple[str, ...]
    created_at: float
    reasons: tuple[str, ...] = ()


def pull_agents_rebase_with_recovery(
    repo: Path,
    git_runner: GitRunner,
    op: str,
    *,
    project_key: str,
) -> _PublicationRebaseResult:
    """Pull with rebase, resolving only conflicts core classifies as regenerable."""

    before_head = _git_value(repo, git_runner, ["rev-parse", "HEAD"], f"{op}.head")
    before_upstream = _git_value(
        repo, git_runner, ["rev-parse", "@{upstream}"], f"{op}.upstream"
    )
    pulled = pull_agents_rebase(repo, git_runner, op)
    if pulled.returncode == 0:
        return _PublicationRebaseResult(pulled)

    unmerged = _unmerged_paths(repo, git_runner, op)
    if unmerged is None or not unmerged:
        return _PublicationRebaseResult(pulled)

    paths = unmerged
    decision_reasons: tuple[str, ...] = ()
    recovery_error: str | None = None
    if before_head is None:
        recovery_error = "could not identify the pre-rebase HEAD"
    else:
        try:
            decision = decide_publication_rebase_conflict(paths)
        except Exception as exc:  # noqa: BLE001 - unknown policy results fail closed.
            decision = None
            recovery_error = f"publication conflict policy failed: {exc}"
        if decision is not None:
            paths = decision.paths
            decision_reasons = decision.reasons
            if decision.action != PUBLICATION_REBASE_ACTION_RESOLVE_UPSTREAM:
                recovery_error = "conflicted paths require manual stale-replay recovery"

    if recovery_error is None and before_head is not None:
        ref = recovery_ref(repo, project_key, before_head, time.time())
        recovery_error = update_and_verify_ref(
            repo,
            ref,
            before_head,
            git_runner,
            op,
        )

    if recovery_error is None:
        for _ in range(_MAX_CONFLICT_RESOLUTIONS):
            current_unmerged = _unmerged_paths(repo, git_runner, op)
            if current_unmerged is None or not current_unmerged:
                recovery_error = "could not inspect the rebase's unmerged paths"
                break
            try:
                current_decision = decide_publication_rebase_conflict(current_unmerged)
            except Exception as exc:  # noqa: BLE001 - unknown policy results fail closed.
                recovery_error = f"publication conflict policy failed: {exc}"
                break
            paths = tuple(dict.fromkeys((*paths, *current_decision.paths)))
            decision_reasons = tuple(
                dict.fromkeys((*decision_reasons, *current_decision.reasons))
            )
            if current_decision.action != PUBLICATION_REBASE_ACTION_RESOLVE_UPSTREAM:
                recovery_error = "conflicted paths require manual stale-replay recovery"
                break

            selected = git_runner(
                repo,
                [
                    "--literal-pathspecs",
                    "checkout",
                    "--ours",
                    "--",
                    *current_decision.paths,
                ],
                op=f"{op}.resolve_upstream",
            )
            if selected.returncode != 0:
                recovery_error = _process_error(
                    "could not select upstream versions of conflicted index pages",
                    selected,
                )
                break
            staged = git_runner(
                repo,
                ["--literal-pathspecs", "add", "--", *current_decision.paths],
                op=f"{op}.stage_resolved_paths",
            )
            if staged.returncode != 0:
                recovery_error = _process_error(
                    "could not stage resolved publication index pages", staged
                )
                break
            continued = git_runner(
                repo,
                ["-c", "core.editor=true", "rebase", "--continue"],
                op=f"{op}.continue_rebase",
            )
            if continued.returncode == 0:
                log.info(
                    "healed publication rebase conflicts for project %s: %s",
                    project_key,
                    ", ".join(paths),
                )
                return _PublicationRebaseResult(
                    subprocess.CompletedProcess(
                        pulled.args,
                        0,
                        (pulled.stdout or "") + (continued.stdout or ""),
                        (pulled.stderr or "") + (continued.stderr or ""),
                    ),
                    conflict_paths=paths,
                    healed=True,
                )
            next_unmerged = _unmerged_paths(repo, git_runner, op)
            if next_unmerged:
                paths = tuple(dict.fromkeys((*paths, *next_unmerged)))
                continue
            recovery_error = _process_error("git rebase --continue failed", continued)
            break
        else:
            recovery_error = (
                "publication rebase exceeded the limit of "
                f"{_MAX_CONFLICT_RESOLUTIONS} conflict resolutions"
            )

    cleanup_error = abort_agents_rebase(repo, git_runner)
    if cleanup_error is not None:
        recovery_error = f"{recovery_error}; rebase abort also failed: {cleanup_error}"
    upstream = (
        _git_value(
            repo, git_runner, ["rev-parse", "@{upstream}"], f"{op}.park_upstream"
        )
        or before_upstream
    )
    marker: _DivergedReplayMarker | None = None
    if before_head is not None and upstream is not None:
        try:
            marker = _write_diverged_replay_marker(
                project_key,
                head=before_head,
                upstream=upstream,
                paths=paths,
                reasons=decision_reasons,
            )
        except Exception as exc:  # noqa: BLE001 - the failure remains reportable.
            recovery_error = f"{recovery_error}; could not save park marker: {exc}"
    if marker is not None:
        _notify_diverged_replay(marker)
    detail = recovery_error or "conflicted publication rebase requires manual recovery"
    message = (
        f"git pull --rebase requires manual recovery: {detail}; "
        f"conflicted paths: {', '.join(paths) or '(unknown)'}"
    )
    return _PublicationRebaseResult(
        subprocess.CompletedProcess(
            pulled.args,
            pulled.returncode or 1,
            pulled.stdout or "",
            f"{pulled.stderr or ''}\n{message}".strip(),
        ),
        failure_stage=PUBLICATION_REBASE_FAILURE_STAGE,
        conflict_paths=paths,
    )


def _write_diverged_replay_marker(
    project_key: str,
    *,
    head: str,
    upstream: str,
    paths: tuple[str, ...],
    reasons: tuple[str, ...] = (),
    now: float | None = None,
) -> _DivergedReplayMarker:
    """Atomically save the local/upstream pair that repeatedly conflicts."""

    timestamp = float(time.time() if now is None else now)
    marker = _DivergedReplayMarker(
        project_key=project_key,
        head=head,
        upstream=upstream,
        paths=tuple(dict.fromkeys(paths)),
        created_at=timestamp,
        reasons=tuple(dict.fromkeys(reasons)),
    )
    atomic_write_json(
        _marker_path(project_key),
        {
            "schema_version": _MARKER_SCHEMA_VERSION,
            "project_key": marker.project_key,
            "head": marker.head,
            "upstream": marker.upstream,
            "paths": list(marker.paths),
            "reasons": list(marker.reasons),
            "created_at": marker.created_at,
            "created_at_utc": datetime.fromtimestamp(timestamp, tz=UTC).isoformat(),
        },
    )
    return marker


def read_diverged_replay_marker(project_key: str) -> _DivergedReplayMarker | None:
    """Read a valid park marker; malformed or missing markers are ignored."""

    path = _marker_path(project_key)
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    if not isinstance(raw, dict) or raw.get("schema_version") != _MARKER_SCHEMA_VERSION:
        return None
    head = raw.get("head")
    upstream = raw.get("upstream")
    created_at = raw.get("created_at")
    paths = raw.get("paths")
    reasons = raw.get("reasons", [])
    if (
        raw.get("project_key") != project_key
        or not isinstance(head, str)
        or not head
        or not isinstance(upstream, str)
        or not upstream
        or not isinstance(created_at, (int, float))
        or not isinstance(paths, list)
        or not all(isinstance(path, str) for path in paths)
        or not isinstance(reasons, list)
        or not all(isinstance(reason, str) for reason in reasons)
    ):
        return None
    return _DivergedReplayMarker(
        project_key=project_key,
        head=head,
        upstream=upstream,
        paths=tuple(paths),
        created_at=float(created_at),
        reasons=tuple(reasons),
    )


def active_diverged_replay_marker(
    project_key: str,
    repo: Path,
    git_runner: GitRunner,
    *,
    now: float | None = None,
) -> _DivergedReplayMarker | None:
    """Return a still-parked marker, clearing it after ref changes or cooldown."""

    marker = read_diverged_replay_marker(project_key)
    if marker is None:
        return None
    observed = time.time() if now is None else now
    if observed - marker.created_at >= PUBLICATION_REPLAY_COOLDOWN_SECONDS:
        _clear_diverged_replay_marker(project_key)
        return None
    head = _git_value(repo, git_runner, ["rev-parse", "HEAD"], "agents_sync.park_head")
    upstream = _git_value(
        repo,
        git_runner,
        ["rev-parse", "@{upstream}"],
        "agents_sync.park_upstream",
    )
    if (
        head is not None
        and upstream is not None
        and (head, upstream)
        != (
            marker.head,
            marker.upstream,
        )
    ):
        _clear_diverged_replay_marker(project_key)
        return None
    return marker


def _clear_diverged_replay_marker(project_key: str) -> None:
    """Remove a park marker after the replay inputs have changed."""

    try:
        _marker_path(project_key).unlink()
    except FileNotFoundError:
        pass


def _marker_path(project_key: str) -> Path:
    validate_sase_project_name(project_key)
    return sase_projects_dir() / project_key / "agent_publication" / _MARKER_FILENAME


def _unmerged_paths(
    repo: Path,
    git_runner: GitRunner,
    op: str,
) -> tuple[str, ...] | None:
    result = git_runner(
        repo,
        ["diff", "--name-only", "--diff-filter=U", "-z"],
        op=f"{op}.unmerged_paths",
    )
    if result.returncode != 0:
        return None
    return tuple(path for path in result.stdout.split("\0") if path)


def _git_value(
    repo: Path,
    git_runner: GitRunner,
    args: list[str],
    op: str,
) -> str | None:
    result = git_runner(repo, args, op=op)
    if result.returncode != 0 or not result.stdout.strip():
        return None
    return result.stdout.strip()


def _process_error(
    prefix: str,
    process: subprocess.CompletedProcess[str],
) -> str:
    detail = process.stderr or process.stdout or f"exit {process.returncode}"
    return f"{prefix}: {detail.strip()}"


def _notify_diverged_replay(marker: _DivergedReplayMarker) -> None:
    """Upsert one actionable notification for a parked publication replay."""

    from sase.notifications.models import Notification, normalize_notification_tags
    from sase.notifications.store import upsert_notification

    timestamp = datetime.now(UTC).isoformat()
    paths = ", ".join(marker.paths) or "(paths unavailable)"
    report_command = (
        ".venv/bin/python tools/agents_publication_recover_replay "
        f"--project {marker.project_key} --expected-head {marker.head} "
        "--backup-dir <backup-dir>"
    )
    apply_command = report_command + " --apply"
    notification = Notification(
        id=str(uuid4()),
        timestamp=timestamp,
        sender="agent-publication",
        icon="!",
        color="#D14343",
        notes=[
            f"Agent publication is parked for {marker.project_key}",
            f"Stuck commit: {marker.head}",
            f"Conflicted paths: {paths}",
            f"Report: {report_command}",
            f"After reviewing the report, apply with: {apply_command}",
            "See 'Stale-replay recovery' in docs/contribute/agents-sidecar-sync.md.",
        ],
        tags=normalize_notification_tags(["agents-sync", "publication", "error"]),
        dedup_key=f"agent_publication_diverged:{marker.project_key}:{marker.head}",
    )
    try:
        upsert_notification(
            notification,
            plus_one_note=f"Still blocked on {paths}",
            plus_one_timestamp=timestamp,
        )
    except Exception:  # noqa: BLE001 - notification failure must not retry the drain.
        log.warning(
            "Could not store diverged publication notification for %s",
            marker.project_key,
            exc_info=True,
        )


__all__ = [
    "PUBLICATION_REBASE_FAILURE_STAGE",
    "PUBLICATION_REPLAY_COOLDOWN_SECONDS",
    "active_diverged_replay_marker",
    "pull_agents_rebase_with_recovery",
    "read_diverged_replay_marker",
]
