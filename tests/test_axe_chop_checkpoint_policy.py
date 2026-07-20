"""Declarative chop checkpoint policy coverage."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from unittest.mock import patch

from sase.axe.chop_policy import (
    ChopPreflight,
    evaluate_chop_preflight,
    finalize_pending_chop_checkpoints,
    record_chop_checkpoint_event,
)
from sase.axe.chop_runner import run_configured_chop_once
from sase.axe.config import AxeConfig, ChopConfig
from sase.core.project_lifecycle_wire import ProjectRecordWire

from tests.axe_chop_runner_helpers import make_script

pytest_plugins = ["tests.axe_chop_runner_fixtures"]


def _project_record(name: str, workspace: Path) -> ProjectRecordWire:
    return ProjectRecordWire(
        schema_version=3,
        project_name=name,
        project_dir=str(workspace.parent / f"state-{name}"),
        project_file=str(workspace.parent / f"state-{name}" / f"{name}.sase"),
        archive_file=None,
        workspace_dir=str(workspace),
        state="enabled",
        state_explicit=False,
        system_managed=False,
        active_claim_count=0,
        launchable=True,
        display_name=name,
        is_project=True,
        vcs_kind="git",
    )


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def _commit(repo: Path, message: str) -> str:
    tracked = repo / "tracked.txt"
    previous = tracked.read_text(encoding="utf-8") if tracked.exists() else ""
    tracked.write_text(previous + message + "\n", encoding="utf-8")
    _git(repo, "add", "tracked.txt")
    _git(
        repo,
        "-c",
        "user.name=SASE Tests",
        "-c",
        "user.email=sase-tests@example.com",
        "commit",
        "-m",
        message,
    )
    return _git(repo, "rev-parse", "HEAD")


def test_git_commits_since_uses_runner_checkpoint_and_accumulates(
    temp_state_dir: Path,
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q")
    first_head = _commit(repo, "first")
    chop = ChopConfig(
        name="audit",
        description="",
        trigger={
            "provider": "git.commits_since",
            "project": "demo",
            "threshold": 2,
            "checkpoint_policy": "on_observation",
        },
    )

    with patch(
        "sase.axe.chop_policy.list_project_records",
        return_value=[_project_record("demo", repo)],
    ):
        first = evaluate_chop_preflight(
            lumberjack_name="docs",
            chop=chop,
            context_file=None,
            scheduled=True,
        )
        assert first.outcome == "fire"
        assert "no prior checkpoint" in first.reason
        record_chop_checkpoint_event("docs", "audit", first, "observed")

        _commit(repo, "second")
        below = evaluate_chop_preflight(
            lumberjack_name="docs",
            chop=chop,
            context_file=None,
            scheduled=True,
        )
        assert below.outcome == "skip"
        assert "1 commits observed" in below.reason

        latest_head = _commit(repo, "third")
        ready = evaluate_chop_preflight(
            lumberjack_name="docs",
            chop=chop,
            context_file=None,
            scheduled=True,
        )

    assert ready.outcome == "fire"
    assert "2 commits observed" in ready.reason
    assert first.decision is not None
    assert first.decision["checkpoint_cursor"] == first_head
    assert ready.decision is not None
    assert ready.decision["checkpoint_cursor"] == latest_head


def test_on_action_success_checkpoint_commits_only_after_success(
    temp_state_dir: Path,
) -> None:
    preflight = ChopPreflight(
        outcome="fire",
        reason="ready",
        checkpoint_enabled=True,
        decision={
            "checkpoint_key": "git.commits_since:demo",
            "checkpoint_cursor": "abc123",
            "checkpoint_policy": "on_action_success",
        },
    )

    record_chop_checkpoint_event("docs", "audit", preflight, "observed")
    checkpoint_path = (
        temp_state_dir / "lumberjacks" / "docs" / "chops" / "audit" / "checkpoint.json"
    )
    pending = json.loads(checkpoint_path.read_text(encoding="utf-8"))
    entry = pending["entries"]["git.commits_since:demo"]
    assert entry["cursor"] == ""
    assert entry["pending_cursor"] == "abc123"

    assert finalize_pending_chop_checkpoints("docs", "audit", "action_succeeded") == 1
    committed = json.loads(checkpoint_path.read_text(encoding="utf-8"))
    entry = committed["entries"]["git.commits_since:demo"]
    assert entry["cursor"] == "abc123"
    assert entry["pending_cursor"] is None


def test_runner_terminal_success_finalizes_pending_checkpoint(
    temp_state_dir: Path,
    tmp_path: Path,
) -> None:
    make_script(tmp_path, "checkpointed", "echo ok\n")
    preflight = ChopPreflight(
        outcome="fire",
        reason="threshold reached",
        checkpoint_enabled=True,
        decision={
            "checkpoint_key": "git.commits_since:demo",
            "checkpoint_cursor": "def456",
            "checkpoint_policy": "on_action_success",
        },
    )

    with (
        patch("sase.axe.chop_runner.find_all_changespecs", return_value=[]),
        patch(
            "sase.axe.chop_runner_script.evaluate_chop_preflight",
            return_value=preflight,
        ),
    ):
        outcome = run_configured_chop_once(
            lumberjack_name="docs",
            chop=ChopConfig(name="checkpointed", description=""),
            axe_config=AxeConfig(chop_script_dirs=[str(tmp_path / "scripts")]),
            source="scheduled",
        )

    assert outcome.status == "success"
    checkpoint_path = (
        temp_state_dir
        / "lumberjacks"
        / "docs"
        / "chops"
        / "checkpointed"
        / "checkpoint.json"
    )
    checkpoint = json.loads(checkpoint_path.read_text(encoding="utf-8"))
    assert checkpoint["entries"]["git.commits_since:demo"]["cursor"] == "def456"
