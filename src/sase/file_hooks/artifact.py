"""Artifact-time file-hook event capture."""

from __future__ import annotations

from collections.abc import Callable, Sequence
import logging
import os
from pathlib import Path
import subprocess

from sase.config.file_hooks import FileHookConfig
from sase.file_hooks.audit import (
    FileHookDispatchResult,
    FileHookProducer,
    complete_file_hook_attempt,
    safe_file_hook_error_diagnostic,
)
from sase.file_hooks.context import (
    classify_repository,
    current_agent_name,
    project_name,
)
from sase.file_hooks.dispatch import dispatch_result
from sase.file_hooks.models import CapturedFileEvent, RepoKind


logger = logging.getLogger(__name__)


def _repository_root(path: Path) -> Path | None:
    candidate = path.expanduser().resolve(strict=False)
    if not candidate.is_dir():
        candidate = candidate.parent
    for directory in (candidate, *candidate.parents):
        if (directory / ".git").exists() or (directory / ".hg").exists():
            return directory
    return None


def capture_artifact_file_event(source_path: str | Path) -> CapturedFileEvent:
    """Capture source-relative matching context before an artifact may move."""
    source = Path(source_path).expanduser().resolve()
    repo_root = _repository_root(source)
    if repo_root is None:
        repo_root = source.parent
        rel_path = source.name
        repo_kind: RepoKind = "external:untracked"
        sidecar_role = None
    else:
        rel_path = source.relative_to(repo_root).as_posix()
        repo_kind, sidecar_role = classify_repository(repo_root)

    provider = None
    try:
        from sase.vcs_provider import get_vcs_provider

        provider = get_vcs_provider(str(repo_root))
    except Exception:
        pass
    project = project_name(
        os.environ.get("SASE_AGENT_PROJECT_FILE"),
        provider,
        str(repo_root),
    )
    return CapturedFileEvent(
        abs_path=str(source),
        repo_root=str(repo_root),
        project=project,
        repo_kind=repo_kind,
        sidecar_role=sidecar_role,
        rel_path=rel_path,
        op="ADD",
        cause="user",
        agent_name=current_agent_name(),
    )


def dispatch_artifact_file_hook_event(
    captured_source: CapturedFileEvent,
    stored_path: str | Path,
    *,
    hooks: Sequence[FileHookConfig] | None,
    popen: Callable[..., subprocess.Popen[str]] | None,
    producer: FileHookProducer,
    dispatcher: Callable[..., FileHookDispatchResult],
) -> FileHookDispatchResult:
    """Dispatch an artifact ADD against the durable stored path."""
    try:
        event = CapturedFileEvent(
            abs_path=str(Path(stored_path).expanduser().resolve()),
            repo_root=captured_source.repo_root,
            project=captured_source.project,
            repo_kind=captured_source.repo_kind,
            sidecar_role=captured_source.sidecar_role,
            rel_path=captured_source.rel_path,
            op="ADD",
            cause=captured_source.cause,
            agent_name=captured_source.agent_name,
        )
    except Exception as exc:
        logger.warning(
            "File-hook artifact event build failed; continuing", exc_info=True
        )
        return complete_file_hook_attempt(
            dispatch_result(
                outcome="producer_error",
                producer=producer,
                events=(captured_source,),
                error=safe_file_hook_error_diagnostic(exc),
                repo_root=captured_source.repo_root,
                sidecar_role=captured_source.sidecar_role,
                agent_name=captured_source.agent_name,
                project=captured_source.project,
            )
        )
    return dispatcher(
        [event],
        hooks=hooks,
        popen=popen,
        producer=producer,
    )


__all__ = ["capture_artifact_file_event", "dispatch_artifact_file_hook_event"]
