"""Best-effort file-hook producers for artifact, commit, and finalizer paths."""

from __future__ import annotations

from collections.abc import Callable, Sequence
import logging
from pathlib import Path
import subprocess
from typing import TYPE_CHECKING

from sase.config.file_hooks import FileHookConfig, load_file_hooks
from sase.file_hooks.audit import (
    FileHookDispatchResult,
    FileHookProducer,
    complete_file_hook_attempt,
    safe_file_hook_error_diagnostic,
)
from sase.file_hooks.engine import (
    CapturedFileEvent,
    capture_artifact_file_event,
    dispatch_artifact_file_hook_event,
    dispatch_commit_file_hook_events,
)

if TYPE_CHECKING:
    from sase.vcs_provider import VCSProvider


logger = logging.getLogger(__name__)


def _error_result(
    *,
    producer: FileHookProducer,
    error: str,
    events: Sequence[CapturedFileEvent] = (),
    commit_sha: str | None = None,
    repo_root: str | None = None,
    sidecar_role: str | None = None,
    agent_name: str | None = None,
    project: str | None = None,
) -> FileHookDispatchResult:
    return complete_file_hook_attempt(
        FileHookDispatchResult(
            outcome="producer_error",
            producer=producer,
            events=tuple(event.identity() for event in events),
            commit_sha=commit_sha,
            error=error,
            repo_root=repo_root,
            sidecar_role=sidecar_role,
            agent_name=agent_name,
            project=project,
        )
    )


def capture_artifact_source(source_path: str | Path) -> CapturedFileEvent | None:
    """Capture matching context before an artifact copy, or record why not.

    Returns the captured event when hooks are configured and capture succeeds.
    ``None`` means either there are no hooks, or an already-audited producer
    error occurred. Never raises.
    """
    source = Path(source_path).expanduser().resolve(strict=False)
    try:
        hooks = load_file_hooks()
    except Exception as exc:
        logger.warning("File-hook config load failed; continuing", exc_info=True)
        _error_result(
            producer="artifact",
            error=safe_file_hook_error_diagnostic(exc),
            repo_root=str(source.parent),
        )
        return None
    if not hooks:
        complete_file_hook_attempt(
            FileHookDispatchResult(
                outcome="no_hooks",
                producer="artifact",
                events=(
                    {
                        "abs_path": str(source),
                        "rel_path": source.name,
                        "op": "ADD",
                    },
                ),
                repo_root=str(source.parent),
            )
        )
        return None
    try:
        return capture_artifact_file_event(source)
    except Exception as exc:
        logger.warning("File-hook artifact capture failed; continuing", exc_info=True)
        _error_result(
            producer="artifact",
            error=safe_file_hook_error_diagnostic(exc),
            repo_root=str(source.parent),
        )
        return None


def produce_artifact_file_hook(
    captured_source: CapturedFileEvent,
    stored_path: str | Path,
    *,
    popen: Callable[..., subprocess.Popen[str]] | None = None,
) -> FileHookDispatchResult:
    """Dispatch an artifact ADD against its durable stored path. Never raises."""
    try:
        hooks = load_file_hooks()
    except Exception as exc:
        logger.warning("File-hook config load failed; continuing", exc_info=True)
        return _error_result(
            producer="artifact",
            error=safe_file_hook_error_diagnostic(exc),
            events=(captured_source,),
            repo_root=captured_source.repo_root,
            sidecar_role=captured_source.sidecar_role,
            agent_name=captured_source.agent_name,
            project=captured_source.project,
        )
    return dispatch_artifact_file_hook_event(
        captured_source,
        stored_path,
        hooks=hooks,
        popen=popen,
        producer="artifact",
    )


def produce_commit_file_hooks(
    *,
    repo_root: str | Path,
    commit_sha: str | None,
    provider: VCSProvider | None = None,
    project_file: str | None = None,
    sidecar_role: str | None = None,
    hooks: Sequence[FileHookConfig] | None = None,
    cause: str = "user",
    agent_name: str | None = None,
    workspace_dir: str | Path | None = None,
    producer: FileHookProducer = "commit",
    popen: Callable[..., subprocess.Popen[str]] | None = None,
) -> FileHookDispatchResult:
    """Capture commit file events and dispatch matching hooks. Never raises."""
    try:
        configured = list(hooks) if hooks is not None else load_file_hooks()
    except Exception as exc:
        logger.warning("File-hook config load failed; continuing", exc_info=True)
        return _error_result(
            producer=producer,
            error=safe_file_hook_error_diagnostic(exc),
            commit_sha=commit_sha,
            repo_root=str(Path(repo_root).expanduser().resolve(strict=False)),
            sidecar_role=sidecar_role,
            agent_name=agent_name,
        )
    return dispatch_commit_file_hook_events(
        repo_root=repo_root,
        commit_sha=commit_sha,
        provider=provider,
        project_file=project_file,
        sidecar_role=sidecar_role,
        hooks=configured,
        cause=cause,
        agent_name=agent_name,
        workspace_dir=workspace_dir,
        producer=producer,
        popen=popen,
    )


def reconcile_commit_file_hooks(
    *,
    repo_root: str | Path,
    commit_sha: str | None,
    workspace_dir: str | Path | None = None,
    sidecar_role: str | None = None,
    agent_name: str | None = None,
    project_file: str | None = None,
    provider: VCSProvider | None = None,
    cause: str = "user",
    popen: Callable[..., subprocess.Popen[str]] | None = None,
) -> FileHookDispatchResult:
    """Idempotently ensure the deterministic commit batch exists.

    Reuses an already-persisted batch without spawning again. If the first
    producer missed persistence, this retries dispatch and records its own
    typed outcome. Attribution is passed explicitly rather than reread from a
    completed-run artifact.
    """
    return produce_commit_file_hooks(
        repo_root=repo_root,
        commit_sha=commit_sha,
        provider=provider,
        project_file=project_file,
        sidecar_role=sidecar_role,
        agent_name=agent_name,
        workspace_dir=workspace_dir,
        cause=cause,
        producer="finalizer",
        popen=popen,
    )


__all__ = [
    "capture_artifact_source",
    "produce_artifact_file_hook",
    "produce_commit_file_hooks",
    "reconcile_commit_file_hooks",
]
