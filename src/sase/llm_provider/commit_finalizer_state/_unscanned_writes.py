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
from ._repository_candidates import repository_candidates

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
    target: str | None = None

    def to_json_dict(self) -> dict[str, object]:
        """Return a JSON-safe mapping for final-context payloads."""

        payload: dict[str, object] = {
            "path": self.path,
            "checkout": self.checkout,
            "repo_relative_path": self.repo_relative_path,
            "status": self.status,
            "repo_name": self.repo_name,
            "action": self.action,
            "instruction": self.instruction,
        }
        if self.target is not None:
            payload["target"] = self.target
        return payload


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
    toplevel is outside the effective finalizer coverage, and is untracked or
    modified. Coverage is derived from the same effective eligibility and
    selection rules as the finalizer, including duplicate names and paths.
    Any error or timeout drops that candidate. This function never raises.
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
        ordered, known_sdd = repository_candidates(project_dir, _as_path(artifact_root))
    except Exception:
        ordered, known_sdd = [], {}
    try:
        normalized_main = finalizer_git.normalize_path(project_dir)
    except Exception:
        normalized_main = project_dir

    try:
        covered = _effective_covered_paths(ordered, known_sdd, normalized_main)
    except Exception:
        covered = set()
    # The main checkout is always scanned; keep it covered even when the
    # shared policy has no dirty facts for it yet.
    covered.add(normalized_main)

    try:
        normalized_project_dir = finalizer_git.normalize_path(project_dir)
    except Exception:
        normalized_project_dir = project_dir

    entries: list[dict[str, object]] = []
    for candidate in candidates:
        try:
            entry = _inspect_candidate(candidate, covered, normalized_project_dir)
        except Exception:
            continue
        if entry is not None:
            entries.append(entry.to_json_dict())
    return tuple(entries)


def _effective_covered_paths(
    ordered: list[tuple[str, str, str]],
    known_sdd: dict[str, str],
    normalized_main: str,
) -> set[str]:
    """Compute effective coverage via the shared Rust policy."""

    from sase.core.unscanned_writes_facade import select_unscanned_coverage

    # Gather status facts once per normalized checkout within the scan.
    unique_paths: list[str] = []
    seen: set[str] = set()
    for _name, path, _kind in ordered:
        if path and path not in seen:
            seen.add(path)
            unique_paths.append(path)
    if normalized_main and normalized_main not in seen:
        seen.add(normalized_main)
        unique_paths.append(normalized_main)

    dirty_paths: list[str] = []
    for path in unique_paths:
        try:
            changed = finalizer_git.git_changed_files(path)
        except Exception:
            continue
        if changed:
            dirty_paths.append(path)

    request: dict[str, Any] = {
        "schema_version": 1,
        "candidates": [
            {"name": name, "path": path, "kind": kind} for name, path, kind in ordered
        ],
        "dirty_paths": dirty_paths,
        "known_sdd_paths": sorted(known_sdd.keys()),
    }
    # Ensure the main checkout participates even when the enumeration
    # omitted it (defensive; the shared enumeration always includes it).
    if not any(c["path"] == normalized_main for c in request["candidates"]):
        request["candidates"].insert(
            0, {"name": "main", "path": normalized_main, "kind": "main"}
        )
    try:
        response = select_unscanned_coverage(request)
    except Exception:
        return set()
    covered = response.get("covered_paths", [])
    if not isinstance(covered, list):
        return set()
    result: set[str] = set()
    for item in covered:
        if isinstance(item, str) and item:
            try:
                result.add(finalizer_git.normalize_path(item))
            except Exception:
                result.add(item)
    return result


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


def _inspect_candidate(
    candidate: str, covered: set[str], run_project_dir: str
) -> _UnscannedWrite | None:
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
    if normalized_toplevel in covered:
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

    repo_name, action, instruction, target = _suggest_fix(
        normalized_toplevel, relpath, run_project_dir
    )
    return _UnscannedWrite(
        path=candidate,
        checkout=normalized_toplevel,
        repo_relative_path=relpath,
        status=status,
        repo_name=repo_name,
        action=action,
        instruction=instruction,
        target=target,
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


def _suggest_fix(
    toplevel: str, relpath: str, run_project_dir: str
) -> tuple[str | None, str, str, str | None]:
    try:
        response = _repair_via_rust(toplevel, relpath, run_project_dir)
    except Exception:
        response = None
    if response is None:
        return (
            None,
            "relocate_or_discard",
            "Open the owning repo with /sase_repo and move the file there, "
            "or delete it if it was scratch.",
            None,
        )
    repo_name = response.get("repo_name")
    action = str(response.get("action") or "relocate_or_discard")
    instruction = str(response.get("instruction") or "").strip() or (
        "Open the owning repo with /sase_repo and move the file there, "
        "or delete it if it was scratch."
    )
    target = response.get("target")
    if not isinstance(repo_name, str):
        repo_name = None
    if not isinstance(target, str):
        target = None
    return (repo_name, action, instruction, target)


def _repair_via_rust(
    toplevel: str, relpath: str, run_project_dir: str
) -> dict[str, Any] | None:
    from sase.core.unscanned_writes_facade import suggest_unscanned_repair
    from sase.repo_inventory import collect_repo_inventory

    from ._workspace_num import (
        workspace_num_for_project_file,
        workspace_num_from_env,
    )

    workspace_num = workspace_num_from_env()
    project_file = os.environ.get("SASE_AGENT_PROJECT_FILE")
    env_project_dir = os.environ.get("SASE_AGENT_PROJECT_DIR") or os.environ.get(
        "SASE_WORKSPACE_DIR", ""
    )
    if workspace_num is None and project_file and env_project_dir:
        try:
            workspace_num = workspace_num_for_project_file(
                project_file, env_project_dir
            )
        except Exception:
            workspace_num = None

    current_project, current_project_key = _current_project_identity(
        run_project_dir or env_project_dir, project_file
    )

    inventory = collect_repo_inventory()
    records: list[dict[str, Any]] = []
    for record in inventory.records:
        try:
            path = finalizer_git.normalize_path(str(record.path))
        except Exception:
            continue
        clones: list[dict[str, Any]] = []
        try:
            for clone in getattr(record, "clones", ()):
                try:
                    clone_path = finalizer_git.normalize_path(str(clone.path))
                except Exception:
                    continue
                try:
                    workspace = int(clone.workspace_num)
                except Exception:
                    continue
                clones.append({"workspace_num": workspace, "path": clone_path})
        except Exception:
            clones = []
        remote = getattr(record, "remote_url", None)
        if remote is not None and not isinstance(remote, str):
            remote = None
        records.append(
            {
                "name": str(getattr(record, "name", "") or ""),
                "project": str(getattr(record, "project", "") or ""),
                "project_key": str(getattr(record, "project_key", "") or ""),
                "path": path,
                "clones": clones,
                "remote_url": remote,
            }
        )

    request: dict[str, Any] = {
        "schema_version": 1,
        "toplevel": toplevel,
        "relpath": relpath,
        "current_project": current_project,
        "current_project_key": current_project_key,
        "records": records,
    }
    if workspace_num is not None:
        request["workspace_num"] = int(workspace_num)
    return suggest_unscanned_repair(request)


def _current_project_identity(
    project_dir: str, project_file: str | None
) -> tuple[str, str]:
    current_project = ""
    current_project_key = ""
    try:
        from sase.repo_inventory import collect_repo_inventory

        if project_dir:
            try:
                normalized_dir = finalizer_git.normalize_path(project_dir)
            except Exception:
                normalized_dir = project_dir
            try:
                inventory = collect_repo_inventory()
            except Exception:
                inventory = None
            if inventory is not None:
                for record in inventory.records:
                    try:
                        if getattr(record, "kind", "") != "primary":
                            continue
                        if (
                            finalizer_git.normalize_path(str(record.path))
                            == normalized_dir
                        ):
                            current_project = str(getattr(record, "project", "") or "")
                            current_project_key = str(
                                getattr(record, "project_key", "") or ""
                            )
                            break
                    except Exception:
                        continue
    except Exception:
        pass
    if not current_project_key:
        try:
            from sase.finalizers.project_identity import (
                resolve_finalizer_project_key,
            )

            key = resolve_finalizer_project_key(Path(project_dir or "."))
            if key:
                current_project_key = key
                if not current_project:
                    current_project = key
        except Exception:
            pass
    if not current_project and project_file:
        try:
            parent = Path(project_file).expanduser().resolve().parent.name
            if parent:
                current_project = parent
                if not current_project_key:
                    current_project_key = parent
        except Exception:
            pass
    return current_project, current_project_key


__all__ = ["find_unscanned_writes"]
