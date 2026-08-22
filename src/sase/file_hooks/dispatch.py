"""Batch construction and detached file-hook dispatch."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import asdict
import hashlib
import json
import logging
from pathlib import Path
import subprocess
import sys
from uuid import uuid4

from sase.config.file_hooks import FileHookConfig, match_events
from sase.file_hooks.audit import (
    FileHookDispatchOutcome,
    FileHookDispatchResult,
    FileHookProducer,
    complete_file_hook_attempt,
    file_hooks_root,
    now_iso,
    safe_file_hook_error_diagnostic,
)
from sase.file_hooks.models import CapturedFileEvent


logger = logging.getLogger(__name__)

BATCH_SCHEMA_VERSION = 1


def _batch_id(
    events: Sequence[CapturedFileEvent],
    hook_names: Sequence[str],
    commit_sha: str | None,
) -> str:
    if commit_sha is None:
        return uuid4().hex
    identity = {
        "commit_sha": commit_sha,
        "events": [asdict(event) for event in events],
        "hooks": list(hook_names),
    }
    encoded = json.dumps(identity, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()[:24]


def _batch_payload(
    *,
    batch_id: str,
    events: Sequence[CapturedFileEvent],
    hooks: Sequence[FileHookConfig],
    commit_sha: str | None,
    producer: FileHookProducer,
) -> dict[str, object]:
    matching_events = [event.matching_event() for event in events]
    planned = match_events(list(hooks), matching_events, producer=producer)
    captured_by_match = {event.matching_event(): event for event in events}
    runs: list[dict[str, object]] = []
    for index, planned_run in enumerate(planned):
        captured = captured_by_match[planned_run.event]
        runs.append(
            {
                "index": index,
                "status": "pending",
                "hook_name": planned_run.hook.name,
                "command": planned_run.hook.command,
                "timeout_seconds": planned_run.hook.timeout_seconds,
                "abs_path": captured.abs_path,
                "repo_root": captured.repo_root,
                "project": captured.project,
                "repo_kind": captured.repo_kind,
                "sidecar_role": captured.sidecar_role,
                "rel_path": captured.rel_path,
                "op": captured.op,
                "cause": captured.cause,
                "agent_name": captured.agent_name,
            }
        )
    return {
        "schema_version": BATCH_SCHEMA_VERSION,
        "batch_id": batch_id,
        "created_at": now_iso(),
        "commit_sha": commit_sha,
        "status": "pending",
        "runs": runs,
    }


def _context_from_events(
    events: Sequence[CapturedFileEvent],
) -> tuple[str | None, str | None, str | None, str | None]:
    if not events:
        return (None, None, None, None)
    first = events[0]
    return (first.repo_root, first.sidecar_role, first.agent_name, first.project)


def dispatch_result(
    *,
    outcome: FileHookDispatchOutcome,
    producer: FileHookProducer,
    events: Sequence[CapturedFileEvent] = (),
    matched_hook_names: Sequence[str] = (),
    configured_hook_count: int = 0,
    commit_sha: str | None = None,
    batch_id: str | None = None,
    batch_path: Path | str | None = None,
    error: str | None = None,
    repo_root: str | None = None,
    sidecar_role: str | None = None,
    agent_name: str | None = None,
    project: str | None = None,
) -> FileHookDispatchResult:
    context_root, context_sidecar, context_agent, context_project = (
        _context_from_events(events)
    )
    return FileHookDispatchResult(
        outcome=outcome,
        producer=producer,
        events=tuple(event.identity() for event in events),
        matched_hook_names=tuple(matched_hook_names),
        configured_hook_count=configured_hook_count,
        commit_sha=commit_sha,
        batch_id=batch_id,
        batch_path=str(batch_path) if batch_path is not None else None,
        error=error,
        repo_root=repo_root or context_root,
        sidecar_role=sidecar_role or context_sidecar,
        agent_name=agent_name or context_agent,
        project=project or context_project,
    )


def _spawn_batch(
    *,
    batch_path: Path,
    batch_id: str,
    repo_root: str,
    popen: Callable[..., subprocess.Popen[str]],
) -> None:
    logs_dir = file_hooks_root() / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    runner_log = logs_dir / f"{batch_id}.log"
    argv = [
        sys.executable,
        "-m",
        "sase",
        "file-hook",
        "exec-batch",
        str(batch_path),
    ]
    try:
        with runner_log.open("ab") as output:
            popen(
                argv,
                cwd=repo_root,
                stdin=subprocess.DEVNULL,
                stdout=output,
                stderr=subprocess.STDOUT,
                start_new_session=True,
                close_fds=True,
            )
    except Exception:
        batch_path.unlink(missing_ok=True)
        raise


def dispatch_file_hook_events(
    events: Sequence[CapturedFileEvent],
    *,
    hooks: Sequence[FileHookConfig] | None,
    commit_sha: str | None,
    popen: Callable[..., subprocess.Popen[str]] | None,
    producer: FileHookProducer,
    repo_root: str | None,
    sidecar_role: str | None,
    agent_name: str | None,
    project: str | None,
    hook_loader: Callable[[], Sequence[FileHookConfig]],
    atomic_create_json: Callable[[Path, dict[str, object]], bool],
) -> FileHookDispatchResult:
    """Match events, persist a batch, spawn the runner, and record the outcome."""
    spawn = popen or subprocess.Popen
    captured = tuple(events)
    try:
        configured = list(hooks) if hooks is not None else list(hook_loader())

        def finish(
            outcome: FileHookDispatchOutcome,
            *,
            matched_hook_names: Sequence[str] = (),
            batch_id: str | None = None,
            batch_path: Path | str | None = None,
            error: str | None = None,
        ) -> FileHookDispatchResult:
            return complete_file_hook_attempt(
                dispatch_result(
                    outcome=outcome,
                    producer=producer,
                    events=captured,
                    matched_hook_names=matched_hook_names,
                    configured_hook_count=len(configured),
                    commit_sha=commit_sha,
                    batch_id=batch_id,
                    batch_path=batch_path,
                    error=error,
                    repo_root=repo_root,
                    sidecar_role=sidecar_role,
                    agent_name=agent_name,
                    project=project,
                )
            )

        if not configured:
            return finish("no_hooks")
        if not captured:
            return finish("no_match")
        planned = match_events(
            configured,
            [event.matching_event() for event in captured],
            producer=producer,
        )
        if not planned:
            return finish("no_match")

        hook_names = [run.hook.name for run in planned]
        matched_names = tuple(dict.fromkeys(hook_names))
        batch_id = _batch_id(captured, hook_names, commit_sha)
        batch_path = file_hooks_root() / "batches" / f"{batch_id}.json"
        payload = _batch_payload(
            batch_id=batch_id,
            events=captured,
            hooks=configured,
            commit_sha=commit_sha,
            producer=producer,
        )
        created = atomic_create_json(batch_path, payload)
        if not created:
            return finish(
                "batch_already_present",
                matched_hook_names=matched_names,
                batch_id=batch_id,
                batch_path=batch_path,
            )
        _spawn_batch(
            batch_path=batch_path,
            batch_id=batch_id,
            repo_root=captured[0].repo_root,
            popen=spawn,
        )
        return finish(
            "batch_dispatched",
            matched_hook_names=matched_names,
            batch_id=batch_id,
            batch_path=batch_path,
        )
    except Exception as exc:
        logger.warning("File-hook dispatch failed; continuing", exc_info=True)
        return complete_file_hook_attempt(
            dispatch_result(
                outcome="producer_error",
                producer=producer,
                events=captured,
                configured_hook_count=len(hooks) if hooks is not None else 0,
                commit_sha=commit_sha,
                error=safe_file_hook_error_diagnostic(exc),
                repo_root=repo_root,
                sidecar_role=sidecar_role,
                agent_name=agent_name,
                project=project,
            )
        )


__all__ = ["BATCH_SCHEMA_VERSION", "dispatch_file_hook_events", "dispatch_result"]
