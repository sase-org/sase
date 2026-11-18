"""Detector for run writes in checkouts the commit finalizer does not scan."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
import subprocess
from typing import Any

from sase.finalizers.declaration_recovery_evidence import (
    MAX_TOOL_CALL_PATHS,
    written_paths_from_tool_calls,
)

from .. import commit_finalizer_git as finalizer_git
from ._scan_roots import commit_scan_roots

_GIT_TOPLEVEL_TIMEOUT_SECONDS = 5
_GIT_STATUS_TIMEOUT_SECONDS = 5


@dataclass(frozen=True)
class _UnscannedWrite:
    """One dirty path in a checkout outside the finalizer scan roots."""

    path: str
    checkout: str
    repo_relative_path: str
    status: str
    repo_name: str | None
    action: str
    instruction: str

    def to_json_dict(self) -> dict[str, object]:
        """Return a JSON-safe mapping for final-context payloads."""

        return {
            "path": self.path,
            "checkout": self.checkout,
            "repo_relative_path": self.repo_relative_path,
            "status": self.status,
            "repo_name": self.repo_name,
            "action": self.action,
            "instruction": self.instruction,
        }


def find_unscanned_writes(
    project_dir: str,
    artifact_root: Path | str | None,
    *,
    extra_paths: tuple[str, ...] = (),
    include_run_paths: bool = True,
) -> tuple[dict[str, object], ...]:
    """Return dirty paths in checkouts the finalizer does not scan.

    Candidates are absolute tool-call writes plus explicit-artifact sources
    plus ``extra_paths``, deduped and capped at ``MAX_TOOL_CALL_PATHS``. A
    candidate is reported only when it exists, sits in a git work tree whose
    toplevel is not a scan root, and is untracked or modified. Any error or
    timeout drops that candidate. This function never raises.
    """

    try:
        return _find_unscanned_writes(
            project_dir,
            artifact_root,
            extra_paths=extra_paths,
            include_run_paths=include_run_paths,
        )
    except Exception:
        return ()


def _find_unscanned_writes(
    project_dir: str,
    artifact_root: Path | str | None,
    *,
    extra_paths: tuple[str, ...],
    include_run_paths: bool,
) -> tuple[dict[str, object], ...]:
    candidates = _collect_candidates(
        artifact_root,
        extra_paths=extra_paths,
        include_run_paths=include_run_paths,
    )
    if not candidates:
        return ()

    try:
        scan_roots = set(commit_scan_roots(project_dir, _as_path(artifact_root)))
    except Exception:
        scan_roots = set()
    try:
        normalized_main = finalizer_git.normalize_path(project_dir)
    except Exception:
        normalized_main = project_dir
    scan_roots.add(normalized_main)

    entries: list[dict[str, object]] = []
    for candidate in candidates:
        try:
            entry = _inspect_candidate(candidate, scan_roots)
        except Exception:
            continue
        if entry is not None:
            entries.append(entry.to_json_dict())
    return tuple(entries)


def _as_path(value: Path | str | None) -> Path | None:
    if value is None or isinstance(value, Path):
        return value
    try:
        return Path(value)
    except Exception:
        return None


def _collect_candidates(
    artifact_root: Path | str | None,
    *,
    extra_paths: tuple[str, ...],
    include_run_paths: bool,
) -> tuple[str, ...]:
    seen: dict[str, None] = {}

    def _add(raw: str | None) -> None:
        if not raw or not isinstance(raw, str):
            return
        text = raw.strip()
        if not text:
            return
        try:
            expanded = str(Path(text).expanduser())
        except Exception:
            return
        if not os.path.isabs(expanded):
            return
        try:
            normalized = finalizer_git.normalize_path(expanded)
        except Exception:
            normalized = expanded
        seen.setdefault(normalized, None)

    if include_run_paths and artifact_root is not None:
        root = _as_path(artifact_root)
        if root is not None:
            try:
                for raw in written_paths_from_tool_calls(root):
                    _add(raw)
            except Exception:
                pass
            try:
                for source in _explicit_artifact_sources(root):
                    _add(source)
            except Exception:
                pass

    for raw in extra_paths or ():
        _add(raw)

    return tuple(list(seen)[:MAX_TOOL_CALL_PATHS])


def _explicit_artifact_sources(artifact_root: Path) -> tuple[str, ...]:
    try:
        from sase.core.artifact_file_facade import list_explicit_artifact_files
        from sase.core.continuation_retention import (
            CONTINUATION_PORTABLE_LABEL_PREFIX,
        )
    except Exception:
        return ()
    try:
        artifacts = list_explicit_artifact_files(artifact_root)
    except Exception:
        return ()
    sources: list[str] = []
    for artifact in artifacts:
        try:
            label = str(getattr(artifact, "label", "") or "")
        except Exception:
            label = ""
        if label.startswith(CONTINUATION_PORTABLE_LABEL_PREFIX):
            continue
        source_path = getattr(artifact, "source_path", None)
        if source_path:
            sources.append(str(source_path))
    return tuple(sources)


def _inspect_candidate(candidate: str, scan_roots: set[str]) -> _UnscannedWrite | None:
    try:
        candidate_path = Path(candidate)
    except Exception:
        return None
    try:
        if not candidate_path.is_file():
            return None
    except Exception:
        return None

    toplevel = _worktree_toplevel(str(candidate_path.parent))
    if toplevel is None:
        return None
    try:
        normalized_toplevel = finalizer_git.normalize_path(toplevel)
    except Exception:
        normalized_toplevel = toplevel
    if normalized_toplevel in scan_roots:
        return None

    status = _candidate_dirty_status(normalized_toplevel, candidate)
    if status is None:
        return None

    try:
        relpath = str(
            Path(candidate)
            .resolve(strict=False)
            .relative_to(Path(normalized_toplevel).resolve(strict=False))
        )
    except Exception:
        try:
            relpath = str(Path(candidate).relative_to(Path(normalized_toplevel)))
        except Exception:
            relpath = os.path.basename(candidate)

    repo_name, action, instruction = _suggest_fix(normalized_toplevel, relpath)
    return _UnscannedWrite(
        path=candidate,
        checkout=normalized_toplevel,
        repo_relative_path=relpath,
        status=status,
        repo_name=repo_name,
        action=action,
        instruction=instruction,
    )


def _worktree_toplevel(directory: str) -> str | None:
    try:
        from sase.workspace_provider.utils import non_interactive_git_env
    except Exception:
        from sase.workspace_provider._utils_git import non_interactive_git_env  # type: ignore[no-redef]

    try:
        result = subprocess.run(
            ["git", "-C", directory, "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            check=False,
            timeout=_GIT_TOPLEVEL_TIMEOUT_SECONDS,
            env=non_interactive_git_env(),
            stdin=subprocess.DEVNULL,
        )
    except Exception:
        return None
    if result.returncode != 0:
        return None
    toplevel = (result.stdout or "").strip()
    return toplevel or None


def _candidate_dirty_status(toplevel: str, candidate: str) -> str | None:
    try:
        from sase.workspace_provider.utils import non_interactive_git_env
    except Exception:
        from sase.workspace_provider._utils_git import non_interactive_git_env  # type: ignore[no-redef]

    try:
        result = subprocess.run(
            [
                "git",
                "--no-optional-locks",
                "-C",
                toplevel,
                "status",
                "--porcelain=v1",
                "--untracked-files=all",
                "--",
                candidate,
            ],
            capture_output=True,
            text=True,
            check=False,
            timeout=_GIT_STATUS_TIMEOUT_SECONDS,
            env=non_interactive_git_env(),
            stdin=subprocess.DEVNULL,
        )
    except Exception:
        return None
    if result.returncode != 0:
        return None
    lines = [
        line.rstrip() for line in (result.stdout or "").splitlines() if line.strip()
    ]
    if not lines:
        return None
    for line in lines:
        code = line[:2] if len(line) >= 2 else ""
        if code.strip() == "?" * len(code.strip()) or code == "??":
            return "untracked"
    first = lines[0]
    if first.startswith("??"):
        return "untracked"
    return "modified"


def _suggest_fix(toplevel: str, relpath: str) -> tuple[str | None, str, str]:
    from typing import Any as _Any

    try:
        record, workspace_num = _match_inventory_record(toplevel)
    except Exception:
        record, workspace_num = None, None
    if record is None:
        return (
            None,
            "relocate_or_discard",
            "Open the owning repo with /sase_repo and move the file there, "
            "or delete it if it was scratch.",
        )
    rec: _Any = record
    name = str(getattr(rec, "name", "") or "").strip() or None
    try:
        own_clone_path = _own_clone_path(rec, workspace_num)
    except Exception:
        own_clone_path = None
    if own_clone_path is not None and own_clone_path == toplevel:
        return (
            name,
            "open",
            f"Run `sase repo open {rec.name}` to register this checkout; "
            "nothing moves.",
        )
    return (
        name,
        "open_and_move",
        f"Run `sase repo open {rec.name}`, then move the file to the same "
        f"repo-relative path ({relpath}) under the printed checkout so the "
        "host commits it.",
    )


def _match_inventory_record(toplevel: str) -> tuple[Any | None, int | None]:
    from sase.repo_inventory import collect_repo_inventory

    from ._workspace_num import (
        workspace_num_for_project_file,
        workspace_num_from_env,
    )

    workspace_num = workspace_num_from_env()
    project_file = os.environ.get("SASE_AGENT_PROJECT_FILE")
    project_dir = os.environ.get("SASE_AGENT_PROJECT_DIR") or os.environ.get(
        "SASE_WORKSPACE_DIR", ""
    )
    if workspace_num is None and project_file and project_dir:
        try:
            workspace_num = workspace_num_for_project_file(project_file, project_dir)
        except Exception:
            workspace_num = None

    inventory = collect_repo_inventory()
    for record in inventory.records:
        candidates: list[str] = []
        try:
            candidates.append(finalizer_git.normalize_path(str(record.path)))
        except Exception:
            pass
        try:
            for clone in getattr(record, "clones", ()):
                candidates.append(finalizer_git.normalize_path(str(clone.path)))
        except Exception:
            continue
        if toplevel in candidates:
            return record, workspace_num
    return None, workspace_num


def _own_clone_path(record: object, workspace_num: int | None) -> str | None:
    if workspace_num is None:
        return None
    try:
        clone = record.clone_for_workspace(workspace_num)  # type: ignore[attr-defined]
    except Exception:
        try:
            from sase.main.repo_handler_common import (
                clone_for_workspace as _clone_for_workspace,
            )

            clone = _clone_for_workspace(record, workspace_num)  # type: ignore[arg-type]
        except Exception:
            return None
    if clone is None:
        return None
    try:
        return finalizer_git.normalize_path(str(clone.path))
    except Exception:
        try:
            fallback = str(getattr(clone, "path", "") or "")
        except Exception:
            return None
        return fallback or None


__all__ = ["find_unscanned_writes"]
