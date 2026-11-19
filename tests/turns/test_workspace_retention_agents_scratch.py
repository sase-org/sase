"""Agents-sidecar publication scratch is not session-owned workspace dirt."""

from __future__ import annotations

import json
from pathlib import Path
import subprocess

from sase.llm_provider.commit_finalizer_baseline import FINALIZER_BASELINE_FILENAME
from sase.llm_provider.commit_finalizer_git import normalize_path
from sase.running_field import get_claimed_workspaces
from sase.sdd.files import set_prompt_qa
from sase.turns.workspace_retention import (
    WorkspaceRetentionRepo,
    settle_stranded_workspace,
)
from tests._running_field_helpers import create_project_file_with_running
from tests.turns._workspace_retention_helpers import (
    claim,
    init_repo,
    owner,
)

_BASE_PROMPT = """---
plan: 202607/test_plan.md
---

Original prompt.
"""
_QA = """%xprompts_enabled:false
### Questions and Answers

#### Q1: Choice

- [x] **A**

%xprompts_enabled:true"""
_AGENTS_REPO_ID = "sdd:agents prompt archive"


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(
        ["git", *args],
        cwd=str(cwd),
        check=True,
        capture_output=True,
        text=True,
    )


def _write_baselines(artifacts: Path, repos: tuple[tuple[str, Path], ...]) -> None:
    artifacts.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": 1,
        "repositories": [
            {
                "repo_id": repo_id,
                "path": normalize_path(str(path)),
                "kind": "primary" if repo_id == "primary" else "sdd",
                "name": repo_id,
                "scope": "run_start",
                "captured_at": "2026-01-01T00:00:00+00:00",
                "fingerprints": {},
            }
            for repo_id, path in repos
        ],
    }
    (artifacts / FINALIZER_BASELINE_FILENAME).write_text(
        json.dumps(payload), encoding="utf-8"
    )


def _owner_with_agents(
    project_file: str,
    checkout: Path,
    artifacts: Path,
    agents: Path,
):
    return owner(
        project_file,
        checkout,
        artifacts,
        repos=(
            WorkspaceRetentionRepo(
                repo_id="primary",
                path=str(checkout),
                is_primary=True,
                positive_custody=True,
            ),
            WorkspaceRetentionRepo(
                repo_id=_AGENTS_REPO_ID,
                path=str(agents),
                positive_custody=True,
            ),
        ),
    )


def _plant_scratch(repo: Path) -> Path:
    scratch = repo / ".sase-v2-stage-deadbeef"
    scratch.mkdir()
    (scratch / "README.md").write_text("staged\n", encoding="utf-8")
    return scratch


def test_settle_only_agents_sidecar_scratch_releases(tmp_path: Path) -> None:
    checkout = init_repo(tmp_path / "ws")
    agents = init_repo(tmp_path / "agents")
    _plant_scratch(agents)
    artifacts = tmp_path / "artifacts"
    _write_baselines(artifacts, (("primary", checkout), (_AGENTS_REPO_ID, agents)))
    project_file = create_project_file_with_running(tmp_path, [claim()])

    result = settle_stranded_workspace(
        _owner_with_agents(project_file, checkout, artifacts, agents)
    )

    assert result.disposition == "release"
    assert get_claimed_workspaces(project_file) == []
    assert (agents / ".sase-v2-stage-deadbeef" / "README.md").is_file()


def test_agents_sidecar_qa_snapshot_is_still_claimed(tmp_path: Path) -> None:
    checkout = init_repo(tmp_path / "ws")
    agents = init_repo(tmp_path / "agents")
    prompt = agents / "prompts" / "202607" / "test_plan.md"
    prompt.parent.mkdir(parents=True)
    prompt.write_text(_BASE_PROMPT, encoding="utf-8")
    _git(agents, "add", "prompts")
    _git(agents, "commit", "-m", "prompt")
    set_prompt_qa(prompt, _QA)
    artifacts = tmp_path / "artifacts"
    _write_baselines(artifacts, (("primary", checkout), (_AGENTS_REPO_ID, agents)))
    project_file = create_project_file_with_running(tmp_path, [claim()])

    result = settle_stranded_workspace(
        _owner_with_agents(project_file, checkout, artifacts, agents)
    )

    assert result.disposition == "retain"
    assert result.reason == "session_owned_dirt"
    assert get_claimed_workspaces(project_file)[0].pinned is True


def test_held_workspace_releases_after_only_scratch_remains(tmp_path: Path) -> None:
    checkout = init_repo(tmp_path / "ws", tracked_dirty=True)
    agents = init_repo(tmp_path / "agents")
    scratch = _plant_scratch(agents)
    artifacts = tmp_path / "artifacts"
    _write_baselines(artifacts, (("primary", checkout), (_AGENTS_REPO_ID, agents)))
    project_file = create_project_file_with_running(tmp_path, [claim()])
    held_owner = _owner_with_agents(project_file, checkout, artifacts, agents)

    first = settle_stranded_workspace(held_owner)
    assert first.disposition == "retain"
    assert get_claimed_workspaces(project_file)[0].pinned is True

    (checkout / "tracked.txt").write_text("base\n", encoding="utf-8")
    second = settle_stranded_workspace(held_owner)

    assert second.disposition == "release"
    assert get_claimed_workspaces(project_file) == []
    assert scratch.is_dir()
