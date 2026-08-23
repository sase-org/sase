"""Shared helpers for file-hook engine tests."""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
from typing import Any
from unittest.mock import MagicMock

import pytest

from sase.config.file_hooks import FileHookConfig, FileHookFilters
from sase.file_hooks.audit import list_file_hook_audits
from sase.file_hooks.engine import (
    CapturedFileEvent,
    dispatch_file_hook_events,
    emit_commit_file_hook_events,
)


def git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def commit(repo: Path, message: str) -> str:
    git(repo, "add", "-A")
    git(repo, "commit", "-m", message)
    return git(repo, "rev-parse", "HEAD")


def init_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init")
    git(repo, "config", "user.email", "hooks@example.com")
    git(repo, "config", "user.name", "Hook Tests")
    git(repo, "remote", "add", "origin", str(repo))
    return repo


def hook(
    name: str,
    command: str = "true",
    *,
    timeout_seconds: float = 120,
    agent_name_globs: tuple[str, ...] | None = None,
    causes: tuple[str, ...] | None = None,
) -> FileHookConfig:
    return FileHookConfig(
        name=name,
        description=None,
        command=command,
        timeout_seconds=timeout_seconds,
        filters=FileHookFilters(agent_name_globs=agent_name_globs, causes=causes),
    )


def event(
    repo: Path,
    path: str = "report.md",
    *,
    agent_name: str | None = None,
    cause: str = "user",
) -> CapturedFileEvent:
    return CapturedFileEvent(
        abs_path=str(repo / path),
        repo_root=str(repo),
        project="sase",
        repo_kind="sidecar:research",
        sidecar_role="research",
        rel_path=path,
        op="ADD",
        cause=cause,
        agent_name=agent_name,
    )


def clear_agent_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SASE_AGENT_NAME", raising=False)
    monkeypatch.delenv("SASE_ARTIFACTS_DIR", raising=False)


def emitted_agent_names(batch_path: Path) -> list[str | None]:
    payload = json.loads(batch_path.read_text(encoding="utf-8"))
    return [run["agent_name"] for run in payload["runs"]]


def stub_detached_spawn(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep the real batch payload while never spawning a runner process."""
    original = dispatch_file_hook_events

    def wrapped(
        events: Any,
        **kwargs: Any,
    ) -> Any:
        if kwargs.get("popen") is None:
            kwargs["popen"] = lambda *args, **spawn_kwargs: MagicMock()
        return original(events, **kwargs)

    monkeypatch.setattr(
        "sase.file_hooks.engine.dispatch_file_hook_events",
        wrapped,
    )


def audits() -> list[str]:
    return [item.outcome for item in list_file_hook_audits()]


def emit_commit(
    monkeypatch: pytest.MonkeyPatch,
    repo: Path,
    sha: str,
    hook_config: FileHookConfig,
) -> Path | None:
    stub_detached_spawn(monkeypatch)
    return emit_commit_file_hook_events(
        repo_root=repo, commit_sha=sha, hooks=[hook_config]
    )
