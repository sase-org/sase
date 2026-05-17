"""Tests for permanent agent-name launch validation."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from sase.agent.launch_validation import (
    AgentNameLaunchCollisionError,
    AgentNameReuseConfirmationRequiredError,
    AgentNameSyntaxError,
    force_reuse_owner_names,
    rewrite_force_reuse_name_directives,
    validate_user_agent_name,
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
    _make_agent(tmp_path, "sasefoo")

    with patch.object(Path, "home", return_value=tmp_path):
        with pytest.raises(AgentNameLaunchCollisionError, match="Try 'sasefoo1'"):
            validate_launch_name_requests(["%name:sasefoo\nDo work"])


def test_forced_reuse_requires_confirmation_on_non_tui_surfaces() -> None:
    with pytest.raises(AgentNameReuseConfirmationRequiredError, match="confirmation"):
        validate_launch_name_requests(["%name:!foo\nDo work"])


def test_user_agent_names_cannot_contain_hyphens() -> None:
    with pytest.raises(AgentNameSyntaxError, match="cannot contain '-'"):
        validate_user_agent_name("foo-bar")


def test_name_directive_rejects_hyphenated_name_before_launch() -> None:
    with pytest.raises(AgentNameSyntaxError, match="foo-bar"):
        validate_launch_name_requests(["%name:foo-bar\nDo work"])


def test_forced_reuse_name_directive_rejects_hyphen_after_bang_strip() -> None:
    with pytest.raises(AgentNameSyntaxError, match="foo-bar"):
        validate_launch_name_requests(["%name:!foo-bar\nDo work"])


def test_tui_agent_rename_rejects_hyphenated_name(tmp_path: Path) -> None:
    from sase.ace.tui.actions.rename import RenameMixin

    artifacts_dir = tmp_path / "artifacts"
    artifacts_dir.mkdir()
    meta_path = artifacts_dir / "agent_meta.json"
    meta_path.write_text(json.dumps({"pid": 123}), encoding="utf-8")

    class FakeAgent:
        identity = ("workflow", "cl", "raw")
        agent_name = None

        def get_artifacts_dir(self) -> str:
            return str(artifacts_dir)

    class FakeApp(RenameMixin):
        def __init__(self) -> None:
            self._agents = [FakeAgent()]
            self.notifications: list[tuple[str, str | None]] = []

        def _get_selected_agent(self) -> FakeAgent:
            return self._agents[0]

        def notify(self, message: str, severity: str | None = None) -> None:
            self.notifications.append((message, severity))

        def push_screen(self, _screen, callback) -> None:
            callback("foo-bar")

        def _refresh_agents_display(self, *, list_changed: bool) -> None:
            raise AssertionError("invalid rename should not refresh")

    app = FakeApp()
    app._set_agent_name()

    assert app.notifications == [
        (
            "Agent name 'foo-bar' cannot contain '-'; hyphen suffixes are "
            "reserved for agent-family phases.",
            "error",
        )
    ]
    assert json.loads(meta_path.read_text(encoding="utf-8")) == {"pid": 123}


def test_launch_agents_from_cwd_cancels_history_and_skips_spawn(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
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

    prompt = "%name:bad-name\n#cd:~ Do work"
    with patch.object(Path, "home", return_value=tmp_path):
        with pytest.raises(AgentNameSyntaxError):
            launch_agents_from_cwd(prompt)

    entries = json.loads(history_path.read_text(encoding="utf-8"))["prompts"]
    assert entries[0]["text"] == prompt
    assert entries[0]["cancelled"] is True
