"""Fail-soft event capture and detached file-hook batch dispatch."""

from __future__ import annotations

from collections.abc import Callable, Sequence
import hashlib
import json
import logging
import os
from dataclasses import asdict, dataclass
from pathlib import Path
import subprocess
import sys
from typing import TYPE_CHECKING, Any, Literal
from uuid import uuid4

from sase.config.file_hooks import (
    FileHookConfig,
    FileHookEvent,
    FileHookOp,
    get_all_file_hooks,
    match_events,
)
from sase.file_hooks.audit import (
    FileHookDispatchOutcome,
    FileHookDispatchResult,
    FileHookProducer,
    atomic_create_json as _atomic_create_json,
    complete_file_hook_attempt,
    file_hooks_root as _file_hooks_root,
    now_iso as _now_iso,
    safe_file_hook_error_diagnostic,
)

if TYPE_CHECKING:
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
    cause: str = "user"
    agent_name: str | None = None

    def matching_event(self) -> FileHookEvent:
        """Return the config matcher's intentionally smaller event view."""
        return FileHookEvent(
            project=self.project,
            repo_kind=self.repo_kind,
            sidecar_role=self.sidecar_role,
            rel_path=self.rel_path,
            op=self.op,
            cause=self.cause,
            agent_name=self.agent_name,
        )

    def identity(self) -> dict[str, Any]:
        """Return the durable, non-secret identity for producer audits."""
        return {
            "abs_path": self.abs_path,
            "repo_root": self.repo_root,
            "project": self.project,
            "repo_kind": self.repo_kind,
            "sidecar_role": self.sidecar_role,
            "rel_path": self.rel_path,
            "op": self.op,
            "cause": self.cause,
            "agent_name": self.agent_name,
        }


def _current_agent_name() -> str | None:
    """Best-effort SASE agent attribution for events captured in-process."""
    try:
        from sase.agent.identity import resolve_local_agent_name

        return resolve_local_agent_name()
    except Exception:
        return None


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
                "cause": captured.cause,
                "agent_name": captured.agent_name,
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


def _context_from_events(
    events: Sequence[CapturedFileEvent],
) -> tuple[str | None, str | None, str | None, str | None]:
    if not events:
        return (None, None, None, None)
    first = events[0]
    return (first.repo_root, first.sidecar_role, first.agent_name, first.project)


def _result(
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
    hooks: Sequence[FileHookConfig] | None = None,
    commit_sha: str | None = None,
    popen: Callable[..., subprocess.Popen[str]] | None = None,
    producer: FileHookProducer = "dispatch",
    repo_root: str | None = None,
    sidecar_role: str | None = None,
    agent_name: str | None = None,
    project: str | None = None,
) -> FileHookDispatchResult:
    """Match *events*, persist a batch, spawn the runner, and record the outcome.

    This producer-side boundary is deliberately fail-soft. A hook engine,
    filesystem, or spawn failure must never alter the result of a commit or
    artifact creation.
    """
    spawn = popen or subprocess.Popen
    captured = tuple(events)
    try:
        configured = list(hooks) if hooks is not None else get_all_file_hooks()

        def finish(
            outcome: FileHookDispatchOutcome,
            *,
            matched_hook_names: Sequence[str] = (),
            batch_id: str | None = None,
            batch_path: Path | str | None = None,
            error: str | None = None,
        ) -> FileHookDispatchResult:
            return complete_file_hook_attempt(
                _result(
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
        matching_events = [event.matching_event() for event in captured]
        planned = match_events(configured, matching_events)
        if not planned:
            return finish("no_match")

        hook_names = [run.hook.name for run in planned]
        matched_names = tuple(dict.fromkeys(hook_names))
        batch_id = _batch_id(captured, hook_names, commit_sha)
        batch_path = _file_hooks_root() / "batches" / f"{batch_id}.json"
        payload = _batch_payload(
            batch_id=batch_id,
            events=captured,
            hooks=configured,
            commit_sha=commit_sha,
        )
        created = _atomic_create_json(batch_path, payload)
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
            _result(
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
            cause=cause,
            agent_name=agent_name,
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
    root = Path(repo_root).expanduser().resolve(strict=False)
    attributed_agent = agent_name if agent_name is not None else _current_agent_name()
    try:
        configured = list(hooks) if hooks is not None else get_all_file_hooks()
        if not configured:
            return complete_file_hook_attempt(
                _result(
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
                _result(
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
        repo_kind, effective_sidecar = _classify_repository(
            root,
            sidecar_role=sidecar_role,
            workspace_dir=workspace_dir,
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
            agent_name=attributed_agent,
            cause=cause,
        )
        return dispatch_file_hook_events(
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
            _result(
                outcome="producer_error",
                producer=producer,
                commit_sha=commit_sha,
                repo_root=str(root),
                sidecar_role=sidecar_role,
                agent_name=attributed_agent,
                error=safe_file_hook_error_diagnostic(exc),
            )
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
        cause="user",
        agent_name=_current_agent_name(),
    )


def dispatch_artifact_file_hook_event(
    captured_source: CapturedFileEvent,
    stored_path: str | Path,
    *,
    hooks: Sequence[FileHookConfig] | None = None,
    popen: Callable[..., subprocess.Popen[str]] | None = None,
    producer: FileHookProducer = "artifact",
) -> FileHookDispatchResult:
    """Typed artifact ADD dispatch against the durable stored path."""
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
            "File-hook artifact event build failed; continuing",
            exc_info=True,
        )
        return complete_file_hook_attempt(
            _result(
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
    return dispatch_file_hook_events(
        [event],
        hooks=hooks,
        popen=popen,
        producer=producer,
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
