"""Tests for permanent agent-name launch validation."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from sase.agent.launch_validation import (
    AgentNameLaunchCollisionError,
    AgentNameReuseConfirmationRequiredError,
    force_reuse_owner_names,
    rewrite_force_reuse_name_directives,
    validate_launch_name_requests,
)


def _make_agent(home: Path, name: str, suffix: str = "run-old") -> Path:
    artifacts_dir = (
        home / ".sase" / "projects" / "proj" / "artifacts" / "ace-run" / suffix
    )
    artifacts_dir.mkdir(parents=True)
    (artifacts_dir / "agent_meta.json").write_text(
        json.dumps({"name": name, "pid": 123}),
        encoding="utf-8",
    )
    return artifacts_dir


def test_extracts_forced_reuse_name_request() -> None:
    names = force_reuse_owner_names(["%name:!foo\nDo work"])

    assert names == ["foo"]


def test_rewrites_forced_reuse_to_normal_name_directive() -> None:
    prompt = "%name:!foo\nDo work"

    assert rewrite_force_reuse_name_directives(prompt) == "%name:foo\nDo work"


def test_collision_validation_uses_registry_suggestion(tmp_path: Path) -> None:
    _make_agent(tmp_path, "sase-foo")

    with patch.object(Path, "home", return_value=tmp_path):
        with pytest.raises(AgentNameLaunchCollisionError, match="Try 'sase-foo1'"):
            validate_launch_name_requests(["%name:sase-foo\nDo work"])


def test_forced_reuse_requires_confirmation_on_non_tui_surfaces() -> None:
    with pytest.raises(AgentNameReuseConfirmationRequiredError, match="confirmation"):
        validate_launch_name_requests(["%name:!foo\nDo work"])


def test_launch_agents_from_cwd_cancels_history_and_skips_spawn(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _make_agent(tmp_path, "sase-foo")

    from sase.history import prompt as prompt_history

    history_path = tmp_path / ".sase" / "prompt_history.json"
    monkeypatch.setattr(prompt_history, "_PROMPT_HISTORY_FILE", history_path)
    monkeypatch.setattr(
        "sase.main.utils.ensure_project_file_and_get_workspace_num",
        lambda: (None, 0, "home"),
    )
    monkeypatch.setattr(
        "sase.agent.launcher.spawn_agent_subprocess",
        lambda **_kwargs: pytest.fail("spawn should not be called"),
    )

    from sase.agent.launcher import launch_agents_from_cwd

    with patch.object(Path, "home", return_value=tmp_path):
        with pytest.raises(AgentNameLaunchCollisionError):
            launch_agents_from_cwd("%name:sase-foo\nDo work")

    entries = json.loads(history_path.read_text(encoding="utf-8"))["prompts"]
    assert entries[0]["text"].startswith("%name:sase-foo\n")
    assert entries[0]["cancelled"] is True
