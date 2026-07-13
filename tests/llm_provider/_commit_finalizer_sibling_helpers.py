"""Shared helpers for commit finalizer linked-repository tests."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from sase.linked_repos import (
    LINKED_REPOS_JSON_ENV,
    OPENED_SIBLINGS_FILENAME,
    record_opened_external_repo,
    record_opened_linked_repo,
)
from sase.llm_provider.commit_finalizer import run_commit_finalizer
from sase.llm_provider.types import InvokeResult
from sase.sibling_repos import SIBLING_REPOS_JSON_ENV, record_opened_sibling


def init_git_repo(path: Path) -> None:
    path.mkdir(parents=True)
    subprocess.run(["git", "init", "-q"], cwd=path, check=True)


def init_bare_remote(path: Path) -> Path:
    subprocess.run(["git", "init", "--bare", "-q", str(path)], check=True)
    return path


def add_origin(repo: Path, remote: Path) -> None:
    subprocess.run(
        ["git", "remote", "add", "origin", str(remote)], cwd=repo, check=True
    )


def set_agent_env(monkeypatch: pytest.MonkeyPatch, project_dir: Path) -> None:
    monkeypatch.setenv("SASE_AGENT_TIMESTAMP", "260521_120000")
    monkeypatch.setenv("CODEX_PROJECT_DIR", str(project_dir))
    monkeypatch.delenv("SASE_DISABLE_COMMIT_STOP_HOOK", raising=False)
    monkeypatch.delenv("SASE_AGENT_PROJECT_FILE", raising=False)
    monkeypatch.delenv(LINKED_REPOS_JSON_ENV, raising=False)
    monkeypatch.delenv(SIBLING_REPOS_JSON_ENV, raising=False)


def set_clean_main(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    build = MagicMock(return_value=(False, [], "", ""))
    monkeypatch.setattr(
        "sase.llm_provider.commit_finalizer.build_commit_details", build
    )
    return build


def isolate_user_config(monkeypatch: pytest.MonkeyPatch, config_dir: Path) -> None:
    """Isolate merged-config loading from the developer's real ``~/.config/sase``.

    The finalizer's config fallback resolves linked repos via
    ``load_merged_config()``, which otherwise folds in the real user
    ``~/.config/sase/sase.yml`` (plus ``sase_*.yml`` overlays) and any
    CWD-local ``sase.yml``.  After the ``linked_repos`` migration the real user
    config carries live ``linked_repos`` entries, so without isolation these
    fallback tests resolve the developer's actual linked repos instead of the
    project-local ``sibling_repos`` they write themselves.  Point ``CONFIG_DIR``
    at an empty directory and disable CWD-local config so the only configured
    entries come from the test's own project ``sase.yml`` (read directly via
    ``_read_project_local_config``).
    """
    config_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr("sase.config.core.CONFIG_DIR", config_dir)
    monkeypatch.setattr("sase.config.core._include_local_config", False)


def run_finalizer(provider: MagicMock, artifacts_dir: Path) -> InvokeResult:
    return run_commit_finalizer(
        provider=provider,
        original_prompt="primary prompt",
        invoke_result=InvokeResult(content="primary response"),
        model_tier="large",
        suppress_output=True,
        model_override=None,
        artifacts_dir=str(artifacts_dir),
    )


def write_tool_call_record(artifacts_dir: Path, record: dict[str, object]) -> None:
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    with open(artifacts_dir / "tool_calls.jsonl", "a", encoding="utf-8") as f:
        f.write(json.dumps(record) + "\n")


def read_result_json(artifacts_dir: Path) -> dict[str, object]:
    return json.loads(
        (artifacts_dir / "commit_finalizer_result.json").read_text(encoding="utf-8")
    )


def mark_opened_sibling(
    monkeypatch: pytest.MonkeyPatch,
    artifacts_dir: Path,
    name: str,
    workspace_dir: Path,
) -> None:
    monkeypatch.setenv("SASE_ARTIFACTS_DIR", str(artifacts_dir))
    record_opened_sibling(name, str(workspace_dir))


def mark_opened_linked(
    monkeypatch: pytest.MonkeyPatch,
    artifacts_dir: Path,
    name: str,
    workspace_dir: Path,
) -> None:
    monkeypatch.setenv("SASE_ARTIFACTS_DIR", str(artifacts_dir))
    record_opened_linked_repo(name, str(workspace_dir))


def mark_opened_external(
    monkeypatch: pytest.MonkeyPatch,
    artifacts_dir: Path,
    name: str,
    workspace_dir: Path,
) -> None:
    monkeypatch.setenv("SASE_ARTIFACTS_DIR", str(artifacts_dir))
    record_opened_external_repo(name, str(workspace_dir))


def write_legacy_opened_siblings_marker(
    artifacts_dir: Path,
    name: str,
    workspace_dir: Path,
) -> None:
    """Write only the legacy ``opened_siblings.json`` marker."""
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    (artifacts_dir / OPENED_SIBLINGS_FILENAME).write_text(
        json.dumps(
            {
                "schema_version": 1,
                "siblings": [
                    {"name": name, "workspace_dir": str(workspace_dir)},
                ],
            }
        ),
        encoding="utf-8",
    )
