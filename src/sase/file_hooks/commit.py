"""Commit-time file-hook event capture."""

from __future__ import annotations

from collections.abc import Callable, Sequence
import logging
import os
from pathlib import Path
import subprocess
from typing import TYPE_CHECKING

from sase.config.file_hooks import FileHookConfig, FileHookOp
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

if TYPE_CHECKING:
    from sase.vcs_provider import VCSProvider


logger = logging.getLogger(__name__)


def canonical_commit_entries(
    raw_entries: Sequence[tuple[str, str]],
) -> list[tuple[FileHookOp, str]]:
    entries: list[tuple[FileHookOp, str]] = []
    for status, path in raw_entries:
        letter = status[:1]
        if letter == "R":
            old_path, separator, new_path = path.partition("\t")
            if separator and new_path:
                entries.extend((("REMOVE", old_path), ("ADD", new_path)))
            else:
                entries.append(("MODIFY", path))
        elif letter == "C":
            _old_path, separator, new_path = path.partition("\t")
            entries.append(("ADD", new_path if separator else path))
        elif letter == "A":
            entries.append(("ADD", path))
        elif letter == "D":
            entries.append(("REMOVE", path))
        else:
            entries.append(("MODIFY", path))
    return sorted(entries, key=lambda item: (item[1], item[0]))


def _root_commit_paths(repo_root: Path, commit_sha: str) -> list[str]:
    result = subprocess.run(
        ["git", "ls-tree", "-r", "--name-only", "-z", commit_sha],
        cwd=repo_root,
        check=True,
        capture_output=True,
        text=True,
        timeout=10,
    )
    return sorted(path for path in result.stdout.split("\0") if path)


def derive_commit_file_events(
    provider: VCSProvider,
    *,
    repo_root: str | Path,
    commit_sha: str,
    project: str,
    repo_kind: RepoKind,
    sidecar_role: str | None,
    agent_name: str | None = None,
    cause: str = "user",
) -> list[CapturedFileEvent]:
    """Derive canonical file operations for one newly created commit."""
    root = Path(repo_root).expanduser().resolve()
    try:
        provider.revision_id(f"{commit_sha}^", str(root))
    except Exception:
        entries: list[tuple[FileHookOp, str]] = [
            ("ADD", path) for path in _root_commit_paths(root, commit_sha)
        ]
    else:
        raw_entries = provider.diff_name_status(
            f"{commit_sha}^",
            commit_sha,
            str(root),
        )
        entries = canonical_commit_entries(raw_entries)

    return [
        CapturedFileEvent(
            abs_path=str(root / rel_path),
            repo_root=str(root),
            project=project,
            repo_kind=repo_kind,
            sidecar_role=sidecar_role,
            rel_path=Path(rel_path).as_posix(),
            op=op,
            cause=cause,
            agent_name=agent_name,
        )
        for op, rel_path in entries
    ]


def dispatch_commit_file_hook_events(
    *,
    repo_root: str | Path,
    commit_sha: str | None,
    provider: VCSProvider | None,
    project_file: str | None,
    sidecar_role: str | None,
    hooks: Sequence[FileHookConfig] | None,
    cause: str,
    agent_name: str | None,
    workspace_dir: str | Path | None,
    producer: FileHookProducer,
    popen: Callable[..., subprocess.Popen[str]] | None,
    hook_loader: Callable[[], Sequence[FileHookConfig]],
    dispatcher: Callable[..., FileHookDispatchResult],
) -> FileHookDispatchResult:
    """Capture and dispatch file events for a newly created repository commit."""
    root = Path(repo_root).expanduser().resolve(strict=False)
    attributed_agent = agent_name if agent_name is not None else current_agent_name()
    try:
        configured = list(hooks) if hooks is not None else list(hook_loader())
        if not configured:
            return complete_file_hook_attempt(
                dispatch_result(
                    outcome="no_hooks",
                    producer=producer,
                    commit_sha=commit_sha,
                    repo_root=str(root),
                    sidecar_role=sidecar_role,
                    agent_name=attributed_agent,
                )
            )
        if not commit_sha:
            return complete_file_hook_attempt(
                dispatch_result(
                    outcome="producer_error",
                    producer=producer,
                    configured_hook_count=len(configured),
                    repo_root=str(root),
                    sidecar_role=sidecar_role,
                    agent_name=attributed_agent,
                    error="commit SHA is missing",
                )
            )
        if provider is None:
            from sase.vcs_provider import get_vcs_provider

            provider = get_vcs_provider(str(root))
        repo_kind, effective_sidecar = classify_repository(
            root,
            sidecar_role=sidecar_role,
            workspace_dir=workspace_dir,
        )
        project = project_name(
            project_file or os.environ.get("SASE_AGENT_PROJECT_FILE"),
            provider,
            str(root),
        )
        events = derive_commit_file_events(
            provider,
            repo_root=root,
            commit_sha=commit_sha,
            project=project,
            repo_kind=repo_kind,
            sidecar_role=effective_sidecar,
            agent_name=attributed_agent,
            cause=cause,
        )
        return dispatcher(
            events,
            hooks=configured,
            commit_sha=commit_sha,
            popen=popen,
            producer=producer,
            repo_root=str(root),
            sidecar_role=effective_sidecar,
            agent_name=attributed_agent,
            project=project,
        )
    except Exception as exc:
        logger.warning("File-hook commit capture failed; continuing", exc_info=True)
        return complete_file_hook_attempt(
            dispatch_result(
                outcome="producer_error",
                producer=producer,
                commit_sha=commit_sha,
                repo_root=str(root),
                sidecar_role=sidecar_role,
                agent_name=attributed_agent,
                error=safe_file_hook_error_diagnostic(exc),
            )
        )


__all__ = [
    "canonical_commit_entries",
    "derive_commit_file_events",
    "dispatch_commit_file_hook_events",
]
