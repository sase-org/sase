"""Fail-soft event capture and detached file-hook batch dispatch."""

from __future__ import annotations

import hashlib
import json
import logging
import os
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
import subprocess
import sys
from typing import TYPE_CHECKING, Literal
from uuid import uuid4

from sase.config.file_hooks import (
    FileHookConfig,
    FileHookEvent,
    FileHookOp,
    get_all_file_hooks,
    match_events,
)
from sase.core.paths import sase_subdir
from sase.core.time import get_timezone

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

    from sase.vcs_provider import VCSProvider


logger = logging.getLogger(__name__)

BATCH_SCHEMA_VERSION = 1
RepoKind = Literal["primary"] | str


@dataclass(frozen=True)
class CapturedFileEvent:
    """One fully attributed file event ready for execution."""

    abs_path: str
    repo_root: str
    project: str
    repo_kind: RepoKind
    sidecar_role: str | None
    rel_path: str
    op: FileHookOp

    def matching_event(self) -> FileHookEvent:
        """Return the config matcher's intentionally smaller event view."""
        return FileHookEvent(
            project=self.project,
            repo_kind=self.repo_kind,
            sidecar_role=self.sidecar_role,
            rel_path=self.rel_path,
            op=self.op,
        )


def _file_hooks_root() -> Path:
    return sase_subdir("file_hooks")


def _now_iso() -> str:
    return datetime.now(get_timezone()).isoformat()


def _atomic_create_json(path: Path, payload: dict[str, object]) -> bool:
    """Create *path* exactly once and return whether this call won."""
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        return False
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(payload, stream, indent=2, sort_keys=True)
            stream.write("\n")
    except Exception:
        path.unlink(missing_ok=True)
        raise
    return True


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
) -> dict[str, object]:
    matching_events = [event.matching_event() for event in events]
    planned = match_events(list(hooks), matching_events)
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
            }
        )
    return {
        "schema_version": BATCH_SCHEMA_VERSION,
        "batch_id": batch_id,
        "created_at": _now_iso(),
        "commit_sha": commit_sha,
        "status": "pending",
        "runs": runs,
    }


def emit_file_hook_events(
    events: Sequence[CapturedFileEvent],
    *,
    hooks: Sequence[FileHookConfig] | None = None,
    commit_sha: str | None = None,
    popen: Callable[..., subprocess.Popen[str]] = subprocess.Popen,
) -> Path | None:
    """Match *events*, persist a batch, and spawn its detached runner.

    This producer-side boundary is deliberately fail-soft. A hook engine,
    filesystem, or spawn failure must never alter the result of a commit or
    artifact creation.
    """
    try:
        configured = list(hooks) if hooks is not None else get_all_file_hooks()
        if not configured or not events:
            return None
        matching_events = [event.matching_event() for event in events]
        planned = match_events(configured, matching_events)
        if not planned:
            return None

        hook_names = [run.hook.name for run in planned]
        batch_id = _batch_id(events, hook_names, commit_sha)
        batch_path = _file_hooks_root() / "batches" / f"{batch_id}.json"
        payload = _batch_payload(
            batch_id=batch_id,
            events=events,
            hooks=configured,
            commit_sha=commit_sha,
        )
        if not _atomic_create_json(batch_path, payload):
            return batch_path

        logs_dir = _file_hooks_root() / "logs"
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
                    cwd=events[0].repo_root,
                    stdin=subprocess.DEVNULL,
                    stdout=output,
                    stderr=subprocess.STDOUT,
                    start_new_session=True,
                    close_fds=True,
                )
        except Exception:
            batch_path.unlink(missing_ok=True)
            raise
        return batch_path
    except Exception:
        logger.warning("File-hook dispatch failed; continuing", exc_info=True)
        return None


def _canonical_commit_entries(
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


def _derive_commit_file_events(
    provider: VCSProvider,
    *,
    repo_root: str | Path,
    commit_sha: str,
    project: str,
    repo_kind: RepoKind,
    sidecar_role: str | None,
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
        entries = _canonical_commit_entries(raw_entries)

    return [
        CapturedFileEvent(
            abs_path=str(root / rel_path),
            repo_root=str(root),
            project=project,
            repo_kind=repo_kind,
            sidecar_role=sidecar_role,
            rel_path=Path(rel_path).as_posix(),
            op=op,
        )
        for op, rel_path in entries
    ]


def _project_name(
    project_file: str | None,
    provider: VCSProvider | None,
    cwd: str,
) -> str:
    key: str | None = None
    if project_file:
        key = Path(project_file).expanduser().parent.name
    if key is None and provider is not None:
        try:
            ok, workspace_name = provider.get_workspace_name(cwd)
            if ok and workspace_name:
                from sase.project_aliases import resolve_project_alias_ref

                key = resolve_project_alias_ref(workspace_name)
        except Exception:
            key = None
    if key is None:
        return "unknown"
    try:
        from sase.project_display_names import project_display_name_for

        return project_display_name_for(key)
    except Exception:
        return key


def _current_agent_workspace_dir() -> Path | None:
    project_dir = os.environ.get("SASE_PROJECT_DIR")
    if project_dir:
        return Path(project_dir).expanduser().resolve(strict=False)
    artifacts_dir = os.environ.get("SASE_ARTIFACTS_DIR")
    if artifacts_dir:
        try:
            from sase.workflows.commit.commit_tracking import agent_workspace_dir

            workspace = agent_workspace_dir(artifacts_dir)
            if workspace:
                return Path(workspace).expanduser().resolve(strict=False)
        except Exception:
            pass
    return None


def _classify_repository(
    repo_root: str | Path,
    *,
    sidecar_role: str | None = None,
    workspace_dir: str | Path | None = None,
) -> tuple[RepoKind, str | None]:
    """Return the repository kind and effective sidecar role."""
    root = Path(repo_root).expanduser().resolve(strict=False)
    if sidecar_role:
        return (f"sidecar:{sidecar_role}", sidecar_role)

    workspace = (
        Path(workspace_dir).expanduser().resolve(strict=False)
        if workspace_dir is not None
        else _current_agent_workspace_dir()
    )
    if workspace is None:
        return ("primary", None)
    if root == workspace:
        return ("primary", None)
    try:
        relative = root.relative_to(workspace / "sase" / "repos")
    except ValueError:
        return ("primary", None)
    if not relative.parts:
        return ("primary", None)
    role = relative.parts[0]
    if role == "linked":
        name = relative.parts[1] if len(relative.parts) > 1 else root.name
        return (f"linked:{name}", None)
    if role == "external":
        name = "/".join(relative.parts[1:]) or root.name
        return (f"external:{name}", None)
    return (f"sidecar:{role}", role)


def emit_commit_file_hook_events(
    *,
    repo_root: str | Path,
    commit_sha: str,
    provider: VCSProvider | None = None,
    project_file: str | None = None,
    sidecar_role: str | None = None,
    hooks: Sequence[FileHookConfig] | None = None,
) -> Path | None:
    """Fail-soft producer seam for a newly created repository commit."""
    configured = list(hooks) if hooks is not None else get_all_file_hooks()
    if not configured:
        return None
    try:
        root = Path(repo_root).expanduser().resolve()
        if provider is None:
            from sase.vcs_provider import get_vcs_provider

            provider = get_vcs_provider(str(root))
        repo_kind, effective_sidecar = _classify_repository(
            root,
            sidecar_role=sidecar_role,
        )
        project = _project_name(
            project_file or os.environ.get("SASE_AGENT_PROJECT_FILE"),
            provider,
            str(root),
        )
        events = _derive_commit_file_events(
            provider,
            repo_root=root,
            commit_sha=commit_sha,
            project=project,
            repo_kind=repo_kind,
            sidecar_role=effective_sidecar,
        )
        return emit_file_hook_events(
            events,
            hooks=configured,
            commit_sha=commit_sha,
        )
    except Exception:
        logger.warning("File-hook commit capture failed; continuing", exc_info=True)
        return None


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
        repo_kind, sidecar_role = _classify_repository(repo_root)

    provider = None
    try:
        from sase.vcs_provider import get_vcs_provider

        provider = get_vcs_provider(str(repo_root))
    except Exception:
        pass
    project = _project_name(
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
    )


def emit_artifact_file_hook_event(
    captured_source: CapturedFileEvent,
    stored_path: str | Path,
) -> Path | None:
    """Emit an artifact ADD while executing against its durable stored path."""
    event = CapturedFileEvent(
        abs_path=str(Path(stored_path).expanduser().resolve()),
        repo_root=captured_source.repo_root,
        project=captured_source.project,
        repo_kind=captured_source.repo_kind,
        sidecar_role=captured_source.sidecar_role,
        rel_path=captured_source.rel_path,
        op="ADD",
    )
    return emit_file_hook_events([event])


__all__ = [
    "BATCH_SCHEMA_VERSION",
    "CapturedFileEvent",
    "capture_artifact_file_event",
    "emit_artifact_file_hook_event",
    "emit_commit_file_hook_events",
    "emit_file_hook_events",
]
