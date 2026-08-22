"""Public compatibility facade for fail-soft file-hook event dispatch."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from pathlib import Path
import subprocess
from typing import TYPE_CHECKING

from sase.config.file_hooks import FileHookConfig, get_all_file_hooks
from sase.file_hooks.artifact import (
    capture_artifact_file_event,
    dispatch_artifact_file_hook_event as _dispatch_artifact_file_hook_event,
)
from sase.file_hooks.audit import (
    FileHookDispatchResult,
    FileHookProducer,
    atomic_create_json as _atomic_create_json,
)
from sase.file_hooks.commit import (
    canonical_commit_entries as _canonical_commit_entries,
    derive_commit_file_events as _derive_commit_file_events,
    dispatch_commit_file_hook_events as _dispatch_commit_file_hook_events,
)
from sase.file_hooks.context import (
    classify_repository as _classify_repository,
    current_agent_name as _current_agent_name,
    current_agent_workspace_dir as _current_agent_workspace_dir,
    project_name as _project_name,
)
from sase.file_hooks.dispatch import (
    BATCH_SCHEMA_VERSION,
    dispatch_file_hook_events as _dispatch_file_hook_events,
)
from sase.file_hooks.models import CapturedFileEvent, RepoKind

if TYPE_CHECKING:
    from sase.vcs_provider import VCSProvider


def dispatch_file_hook_events(
    events: Sequence[CapturedFileEvent],
    *,
    hooks: Sequence[FileHookConfig] | None = None,
    commit_sha: str | None = None,
    popen: Callable[..., subprocess.Popen[str]] | None = None,
    producer: FileHookProducer = "dispatch",
    repo_root: str | None = None,
    sidecar_role: str | None = None,
    agent_name: str | None = None,
    project: str | None = None,
) -> FileHookDispatchResult:
    """Match events, persist a batch, spawn the runner, and record the outcome.

    This producer-side boundary is deliberately fail-soft. A hook engine,
    filesystem, or spawn failure must never alter the result of a commit or
    artifact creation.
    """
    return _dispatch_file_hook_events(
        events,
        hooks=hooks,
        commit_sha=commit_sha,
        popen=popen,
        producer=producer,
        repo_root=repo_root,
        sidecar_role=sidecar_role,
        agent_name=agent_name,
        project=project,
        hook_loader=get_all_file_hooks,
        atomic_create_json=_atomic_create_json,
    )


def emit_file_hook_events(
    events: Sequence[CapturedFileEvent],
    *,
    hooks: Sequence[FileHookConfig] | None = None,
    commit_sha: str | None = None,
    popen: Callable[..., subprocess.Popen[str]] | None = None,
    producer: FileHookProducer = "dispatch",
) -> Path | None:
    """Compatibility wrapper around :func:`dispatch_file_hook_events`."""
    result = dispatch_file_hook_events(
        events,
        hooks=hooks,
        commit_sha=commit_sha,
        popen=popen,
        producer=producer,
    )
    return Path(result.batch_path) if result.batch_path else None


def dispatch_commit_file_hook_events(
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
    """Typed fail-soft producer seam for a newly created repository commit."""
    return _dispatch_commit_file_hook_events(
        repo_root=repo_root,
        commit_sha=commit_sha,
        provider=provider,
        project_file=project_file,
        sidecar_role=sidecar_role,
        hooks=hooks,
        cause=cause,
        agent_name=agent_name,
        workspace_dir=workspace_dir,
        producer=producer,
        popen=popen,
        hook_loader=get_all_file_hooks,
        dispatcher=dispatch_file_hook_events,
    )


def emit_commit_file_hook_events(
    *,
    repo_root: str | Path,
    commit_sha: str,
    provider: VCSProvider | None = None,
    project_file: str | None = None,
    sidecar_role: str | None = None,
    hooks: Sequence[FileHookConfig] | None = None,
    cause: str = "user",
    agent_name: str | None = None,
    workspace_dir: str | Path | None = None,
    producer: FileHookProducer = "commit",
    popen: Callable[..., subprocess.Popen[str]] | None = None,
) -> Path | None:
    """Fail-soft producer seam for a newly created repository commit."""
    result = dispatch_commit_file_hook_events(
        repo_root=repo_root,
        commit_sha=commit_sha,
        provider=provider,
        project_file=project_file,
        sidecar_role=sidecar_role,
        hooks=hooks,
        cause=cause,
        agent_name=agent_name,
        workspace_dir=workspace_dir,
        producer=producer,
        popen=popen,
    )
    return Path(result.batch_path) if result.batch_path else None


def dispatch_artifact_file_hook_event(
    captured_source: CapturedFileEvent,
    stored_path: str | Path,
    *,
    hooks: Sequence[FileHookConfig] | None = None,
    popen: Callable[..., subprocess.Popen[str]] | None = None,
    producer: FileHookProducer = "artifact",
) -> FileHookDispatchResult:
    """Typed artifact ADD dispatch against the durable stored path."""
    return _dispatch_artifact_file_hook_event(
        captured_source,
        stored_path,
        hooks=hooks,
        popen=popen,
        producer=producer,
        dispatcher=dispatch_file_hook_events,
    )


def emit_artifact_file_hook_event(
    captured_source: CapturedFileEvent,
    stored_path: str | Path,
) -> Path | None:
    """Emit an artifact ADD while executing against its durable stored path."""
    result = dispatch_artifact_file_hook_event(captured_source, stored_path)
    return Path(result.batch_path) if result.batch_path else None


__all__ = [
    "BATCH_SCHEMA_VERSION",
    "CapturedFileEvent",
    "capture_artifact_file_event",
    "dispatch_artifact_file_hook_event",
    "dispatch_commit_file_hook_events",
    "dispatch_file_hook_events",
    "emit_artifact_file_hook_event",
    "emit_commit_file_hook_events",
    "emit_file_hook_events",
]
