"""Provider-neutral commit finalization for SASE-launched agents."""

from __future__ import annotations

import json
import os
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Literal

from sase.commit_instructions import (
    build_commit_details,
    build_commit_instruction_message,
    build_name_instruction_text,
)
from sase.config.core import load_merged_config
from sase.env_contracts import SASE_ACTIVE_PROJECT_DIR_ENV
from sase.sibling_repos import SIBLING_REPOS_JSON_ENV, sibling_repo_metadata_from_env

from .base import LLMProvider
from .types import InvokeResult, ModelTier

_WORKSPACE_ENV_VARS: tuple[str, ...] = (
    "SASE_GIT_WORKSPACE_DIR",
    "SASE_CD_WORKSPACE_DIR",
)
_WORKSPACE_NUM_ENV_VARS: tuple[str, ...] = (
    "SASE_AGENT_WORKSPACE_NUM",
    "SASE_GIT_WORKSPACE_NUM",
    "SASE_CD_WORKSPACE_NUM",
)
_PROVIDER_PROJECT_ENV_VARS: tuple[str, ...] = (
    "CODEX_PROJECT_DIR",
    SASE_ACTIVE_PROJECT_DIR_ENV,
    "CLAUDE_PROJECT_DIR",
    "QWEN_PROJECT_DIR",
    "GEMINI_PROJECT_DIR",
    "OPENCODE_PROJECT_DIR",
)
_DEFAULT_ENABLED = True
_DEFAULT_MAX_PASSES = 2

_FinalizerStatus = Literal["skipped", "clean", "finalized", "failed"]


class _CommitFinalizerError(Exception):
    """Raised when the commit finalizer cannot prove the workspace is clean."""


@dataclass(frozen=True)
class _CommitFinalizerConfig:
    enabled: bool = _DEFAULT_ENABLED
    max_passes: int = _DEFAULT_MAX_PASSES


@dataclass(frozen=True)
class _CommitFinalizerResult:
    status: _FinalizerStatus
    reason: str
    project_dir: str | None
    passes: int
    changed_files: list[str]
    error: str | None = None


@dataclass(frozen=True)
class _DirtyRepo:
    name: str
    path: str
    changed_files: tuple[str, ...]
    kind: Literal["main", "sibling"]


@dataclass(frozen=True)
class _DirtyState:
    project_dir: str
    repos: tuple[_DirtyRepo, ...]
    details: str


@dataclass(frozen=True)
class _SiblingTarget:
    name: str
    workspace_dir: str


def run_commit_finalizer(
    *,
    provider: LLMProvider,
    original_prompt: str,
    invoke_result: InvokeResult,
    model_tier: ModelTier,
    suppress_output: bool,
    model_override: str | None,
    artifacts_dir: str | None = None,
) -> InvokeResult:
    """Run bounded commit finalization after a successful provider turn."""
    config = _load_finalizer_config()
    artifact_root = _artifact_root(artifacts_dir)

    if os.environ.get("SASE_DISABLE_COMMIT_STOP_HOOK"):
        _write_result(
            artifact_root,
            _CommitFinalizerResult(
                status="skipped",
                reason="disabled_by_env",
                project_dir=None,
                passes=0,
                changed_files=[],
            ),
        )
        return invoke_result

    if not config.enabled:
        _write_result(
            artifact_root,
            _CommitFinalizerResult(
                status="skipped",
                reason="disabled_by_config",
                project_dir=None,
                passes=0,
                changed_files=[],
            ),
        )
        return invoke_result

    if not os.environ.get("SASE_AGENT_TIMESTAMP"):
        _write_result(
            artifact_root,
            _CommitFinalizerResult(
                status="skipped",
                reason="outside_sase_agent",
                project_dir=None,
                passes=0,
                changed_files=[],
            ),
        )
        return invoke_result

    project_dir = _resolve_finalizer_project_dir()
    dirty_state = _collect_dirty_state(project_dir)
    if not dirty_state.repos:
        _write_result(
            artifact_root,
            _CommitFinalizerResult(
                status="clean",
                reason="no_changes",
                project_dir=project_dir,
                passes=0,
                changed_files=[],
            ),
        )
        return invoke_result

    accumulated_content = invoke_result.content
    accumulated_usage = invoke_result.usage

    for pass_number in range(1, config.max_passes + 1):
        follow_up_prompt = _build_follow_up_prompt(
            original_prompt=original_prompt,
            accumulated_response=accumulated_content,
            details=dirty_state.details,
            pass_number=pass_number,
            max_passes=config.max_passes,
        )
        _write_text(
            artifact_root,
            f"commit_finalizer_pass_{pass_number}_prompt.md",
            follow_up_prompt,
        )

        follow_up = provider.invoke(
            follow_up_prompt,
            model_tier=model_tier,
            suppress_output=suppress_output,
            model_override=model_override,
        )
        _write_text(
            artifact_root,
            f"commit_finalizer_pass_{pass_number}_response.md",
            follow_up.content,
        )

        accumulated_content = _append_response(
            accumulated_content,
            follow_up.content,
        )
        accumulated_usage = _merge_usage(accumulated_usage, follow_up.usage)

        dirty_state = _collect_dirty_state(project_dir)
        if not dirty_state.repos:
            _write_result(
                artifact_root,
                _CommitFinalizerResult(
                    status="finalized",
                    reason="clean_after_pass",
                    project_dir=project_dir,
                    passes=pass_number,
                    changed_files=[],
                ),
            )
            return InvokeResult(content=accumulated_content, usage=accumulated_usage)

    error = _failure_message(dirty_state, config.max_passes)
    _write_result(
        artifact_root,
        _CommitFinalizerResult(
            status="failed",
            reason="dirty_after_max_passes",
            project_dir=project_dir,
            passes=config.max_passes,
            changed_files=_result_changed_files(dirty_state),
            error=error,
        ),
    )
    raise _CommitFinalizerError(error)


def _resolve_finalizer_project_dir() -> str:
    """Resolve the workspace the finalizer should inspect."""
    for key in _PROVIDER_PROJECT_ENV_VARS:
        candidate = os.environ.get(key)
        if candidate:
            return candidate
    workspace = _workspace_env_value()
    if workspace:
        return workspace
    return os.getcwd()


def _workspace_env_value() -> str | None:
    for key in _WORKSPACE_ENV_VARS:
        value = os.environ.get(key)
        if value:
            return value
    return None


def _collect_dirty_state(project_dir: str) -> _DirtyState:
    has_main_changes, main_files, main_instruction, main_details = build_commit_details(
        project_dir
    )

    main_repo = (
        _DirtyRepo(
            name="main",
            path=_normalize_path(project_dir),
            changed_files=tuple(main_files),
            kind="main",
        )
        if has_main_changes
        else None
    )
    sibling_repos = tuple(_dirty_configured_sibling_repos(project_dir))
    repos: list[_DirtyRepo] = []
    if main_repo is not None:
        repos.append(main_repo)
    repos.extend(sibling_repos)
    details = _build_dirty_details(
        main_details=main_details,
        main_instruction=main_instruction,
        main_repo=main_repo,
        sibling_repos=sibling_repos,
    )
    return _DirtyState(
        project_dir=_normalize_path(project_dir),
        repos=tuple(repos),
        details=details,
    )


def _dirty_configured_sibling_repos(project_dir: str) -> list[_DirtyRepo]:
    dirty: list[_DirtyRepo] = []
    for target in _configured_sibling_targets(project_dir):
        changed_files = _git_changed_files(target.workspace_dir)
        if not changed_files:
            continue
        dirty.append(
            _DirtyRepo(
                name=target.name,
                path=target.workspace_dir,
                changed_files=tuple(changed_files),
                kind="sibling",
            )
        )
    return dirty


def _configured_sibling_targets(project_dir: str) -> list[_SiblingTarget]:
    if SIBLING_REPOS_JSON_ENV in os.environ:
        return _sibling_targets_from_env()
    return _sibling_targets_from_config(project_dir)


def _sibling_targets_from_env() -> list[_SiblingTarget]:
    targets: list[_SiblingTarget] = []
    for index, item in enumerate(sibling_repo_metadata_from_env(os.environ), start=1):
        workspace_dir = item.get("workspace_dir")
        if not isinstance(workspace_dir, str) or not workspace_dir.strip():
            continue
        name = item.get("name")
        if not isinstance(name, str) or not name.strip():
            name = f"sibling_{index}"
        targets.append(
            _SiblingTarget(
                name=name.strip(),
                workspace_dir=_normalize_path(workspace_dir),
            )
        )
    return targets


def _sibling_targets_from_config(project_dir: str) -> list[_SiblingTarget]:
    project_file = os.environ.get("SASE_AGENT_PROJECT_FILE")
    if not project_file:
        return []

    workspace_num = _workspace_num_for_project_file(project_file, project_dir)
    if workspace_num is None:
        return []

    try:
        from sase.sibling_repos import resolve_sibling_repos_for_project

        resolution = resolve_sibling_repos_for_project(
            project_file=project_file,
            workspace_dir=project_dir,
            workspace_num=workspace_num,
            materialize=False,
        )
    except Exception:
        return []

    return [
        _SiblingTarget(
            name=repo.name, workspace_dir=_normalize_path(repo.workspace_dir)
        )
        for repo in resolution.repos
    ]


def _workspace_num_for_project_file(project_file: str, project_dir: str) -> int | None:
    env_num = _workspace_num_from_env()
    if env_num is not None:
        return env_num

    try:
        from sase.workspace_provider.utils import parse_workspace_dir

        primary_dir = parse_workspace_dir(project_file)
    except Exception:
        return None

    if not primary_dir:
        return None

    primary_path = Path(_normalize_path(primary_dir))
    project_path = Path(_normalize_path(project_dir))
    if project_path == primary_path:
        return 0
    if project_path.parent != primary_path.parent:
        return None

    prefix = f"{primary_path.name}_"
    if not project_path.name.startswith(prefix):
        return None
    suffix = project_path.name[len(prefix) :]
    if not suffix.isdigit():
        return None
    return int(suffix)


def _workspace_num_from_env() -> int | None:
    for key in _WORKSPACE_NUM_ENV_VARS:
        raw = os.environ.get(key)
        if not raw:
            continue
        try:
            return int(raw)
        except ValueError:
            continue
    return None


def _git_changed_files(repo_dir: str) -> list[str]:
    if not Path(repo_dir).is_dir():
        return []
    try:
        result = subprocess.run(
            [
                "git",
                "-C",
                repo_dir,
                "status",
                "--porcelain=v1",
                "--untracked-files=all",
            ],
            capture_output=True,
            text=True,
            check=False,
            timeout=20,
        )
    except Exception:
        return []
    if result.returncode != 0:
        return []
    return _changed_files_from_git_status(result.stdout)


def _changed_files_from_git_status(status_text: str) -> list[str]:
    changed: list[str] = []
    for raw_line in status_text.splitlines():
        line = raw_line.rstrip()
        if not line:
            continue
        changed.append(line[3:] if len(line) > 3 else line)
    return changed


def _build_dirty_details(
    *,
    main_details: str,
    main_instruction: str,
    main_repo: _DirtyRepo | None,
    sibling_repos: tuple[_DirtyRepo, ...],
) -> str:
    if main_repo is not None and not sibling_repos and main_details:
        return main_details

    repos: list[_DirtyRepo] = []
    if main_repo is not None:
        repos.append(main_repo)
    repos.extend(sibling_repos)
    if not repos:
        return ""

    lines = ["Uncommitted changes detected in configured repositories:"]
    for repo in repos:
        label = "main workspace" if repo.kind == "main" else f"sibling repo {repo.name}"
        lines.append(f"- {label}: {repo.path}")
        lines.extend(f"  - {path}" for path in repo.changed_files[:20])
        if len(repo.changed_files) > 20:
            lines.append(f"  - ... ({len(repo.changed_files)} total)")

    if main_repo is not None and main_instruction:
        lines.extend(["", "Main workspace commit instructions:", main_instruction])

    if sibling_repos:
        lines.extend(["", "Sibling repository commit instructions:"])
        for repo in sibling_repos:
            lines.append(
                f"- For `{repo.name}`, run `cd {repo.path}` before using "
                "your /sase_git_commit skill."
            )
        lines.append(_sibling_commit_instruction())
        lines.append(
            "After each sibling commit, run `git status --short --branch` in "
            "that sibling repo and make sure it is clean before continuing."
        )

    return "\n".join(lines)


def _sibling_commit_instruction() -> str:
    method = os.environ.get("SASE_COMMIT_METHOD", "")
    instruction = build_commit_instruction_message(
        "/sase_git_commit", method, os.environ.get("SASE_BEAD_ID")
    )
    name_instruction = build_name_instruction_text()
    if name_instruction:
        instruction += " " + name_instruction
    return instruction


def _result_changed_files(dirty_state: _DirtyState) -> list[str]:
    if len(dirty_state.repos) == 1 and dirty_state.repos[0].kind == "main":
        return list(dirty_state.repos[0].changed_files)

    changed: list[str] = []
    for repo in dirty_state.repos:
        changed.extend(f"{repo.name}:{path}" for path in repo.changed_files)
    return changed


def _normalize_path(path: str) -> str:
    return str(Path(path).expanduser().resolve(strict=False))


def _load_finalizer_config() -> _CommitFinalizerConfig:
    try:
        config = load_merged_config()
    except Exception:
        return _CommitFinalizerConfig()

    commit_config = config.get("commit", {})
    if not isinstance(commit_config, dict):
        return _CommitFinalizerConfig()
    finalizer_config = commit_config.get("finalizer", {})
    if not isinstance(finalizer_config, dict):
        return _CommitFinalizerConfig()

    enabled = finalizer_config.get("enabled", _DEFAULT_ENABLED)
    max_passes = finalizer_config.get("max_passes", _DEFAULT_MAX_PASSES)
    return _CommitFinalizerConfig(
        enabled=enabled if isinstance(enabled, bool) else _DEFAULT_ENABLED,
        max_passes=_normalize_max_passes(max_passes),
    )


def _normalize_max_passes(value: Any) -> int:
    if isinstance(value, bool):
        return _DEFAULT_MAX_PASSES
    try:
        max_passes = int(value)
    except (TypeError, ValueError):
        return _DEFAULT_MAX_PASSES
    return max(1, max_passes)


def _build_follow_up_prompt(
    *,
    original_prompt: str,
    accumulated_response: str,
    details: str,
    pass_number: int,
    max_passes: int,
) -> str:
    return (
        f"{original_prompt}\n\n"
        f"--- Work So Far ---\n{accumulated_response}\n\n"
        f"--- Commit Finalizer Pass {pass_number} of {max_passes} ---\n"
        f"{details}\n\n"
        "After handling the commit requirement, respond with a concise summary "
        "of what you did."
    )


def _append_response(existing: str, new: str) -> str:
    return (existing + "\n\n" + new.strip()).strip()


def _merge_usage(
    first: dict[str, int] | None,
    second: dict[str, int] | None,
) -> dict[str, int] | None:
    if first is None:
        return dict(second) if second is not None else None
    if second is None:
        return dict(first)
    merged = dict(first)
    for key, value in second.items():
        merged[key] = merged.get(key, 0) + value
    return merged


def _failure_message(
    dirty_state: _DirtyState,
    max_passes: int,
) -> str:
    changed_files = _result_changed_files(dirty_state)
    listed_files = ", ".join(changed_files[:10]) or "(unable to list changed files)"
    if len(changed_files) > 10:
        listed_files += f", ... ({len(changed_files)} total)"
    repo_paths = ", ".join(f"{repo.name}={repo.path}" for repo in dirty_state.repos)
    return (
        "Commit finalizer failed: uncommitted changes remain after "
        f"{max_passes} finalizer pass(es) in {repo_paths}: {listed_files}."
    )


def _artifact_root(artifacts_dir: str | None) -> Path | None:
    root = artifacts_dir or os.environ.get("SASE_ARTIFACTS_DIR")
    return Path(root) if root else None


def _write_text(root: Path | None, filename: str, content: str) -> None:
    if root is None:
        return
    try:
        root.mkdir(parents=True, exist_ok=True)
        (root / filename).write_text(content, encoding="utf-8")
    except OSError:
        pass


def _write_result(root: Path | None, result: _CommitFinalizerResult) -> None:
    if root is None:
        return
    try:
        root.mkdir(parents=True, exist_ok=True)
        (root / "commit_finalizer_result.json").write_text(
            json.dumps(asdict(result), indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    except OSError:
        pass
