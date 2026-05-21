"""Provider-neutral commit finalization for SASE-launched agents."""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Literal

from sase.commit_instructions import build_commit_details
from sase.config.core import load_merged_config
from sase.env_contracts import SASE_ACTIVE_PROJECT_DIR_ENV

from .base import LLMProvider
from .types import InvokeResult, ModelTier

_WORKSPACE_ENV_VARS: tuple[str, ...] = (
    "SASE_GIT_WORKSPACE_DIR",
    "SASE_CD_WORKSPACE_DIR",
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
    has_changes, changed_files, _, details = build_commit_details(project_dir)
    if not has_changes:
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
            details=details,
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

        has_changes, changed_files, _, details = build_commit_details(project_dir)
        if not has_changes:
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

    error = _failure_message(project_dir, changed_files, config.max_passes)
    _write_result(
        artifact_root,
        _CommitFinalizerResult(
            status="failed",
            reason="dirty_after_max_passes",
            project_dir=project_dir,
            passes=config.max_passes,
            changed_files=changed_files,
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
    project_dir: str,
    changed_files: list[str],
    max_passes: int,
) -> str:
    listed_files = ", ".join(changed_files[:10]) or "(unable to list changed files)"
    if len(changed_files) > 10:
        listed_files += f", ... ({len(changed_files)} total)"
    return (
        "Commit finalizer failed: uncommitted changes remain in "
        f"{project_dir} after {max_passes} finalizer pass(es): {listed_files}."
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
