"""Tests for the dismissed-agents-index write in :func:`kill_named_agent`.

When the user kills an agent via the Telegram "Kill" button, gchat, or
``sase agent kill``, the agent ought to disappear from ``sase ace``'s
agents tab the same way an ``x`` press in the TUI does. The kill path
must therefore add the agent's identity to ``~/.sase/dismissed_agents.json``
so the loader filters out the eventual ``done.json`` with
``outcome="failed"``.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from contextlib import AbstractContextManager
from pathlib import Path
from unittest.mock import patch

import pytest

from sase.agent.names._common import NamedAgent
from sase.agent.running import kill_named_agent


@pytest.fixture(autouse=True)
def _isolated_dismissed_index(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Iterator[Path]:
    """Redirect the dismissed-agents JSON to a per-test path.

    ``sase.ace.dismissed_agents._DISMISSED_AGENTS_FILE`` is bound at import
    time, so tests must override it explicitly to avoid clobbering the real
    ``~/.sase/dismissed_agents.json``.
    """
    from sase.ace import dismissed_agents as mod

    isolated = tmp_path / "dismissed_agents.json"
    monkeypatch.setattr(mod, "_DISMISSED_AGENTS_FILE", isolated)
    yield isolated


def _setup_home_agent(home: Path, *, with_cl_name: bool = False) -> Path:
    artifacts_dir = (
        home
        / ".sase"
        / "projects"
        / "home"
        / "artifacts"
        / "ace-run"
        / "20260510120000"
    )
    artifacts_dir.mkdir(parents=True)
    (artifacts_dir / "running.json").write_text(json.dumps({"pid": 11111}))
    meta: dict[str, object] = {"name": "home_agent", "pid": 11111}
    if with_cl_name:
        meta["cl_name"] = "home_feature"
    (artifacts_dir / "agent_meta.json").write_text(json.dumps(meta))
    return artifacts_dir


def _setup_nonhome_agent(home: Path) -> tuple[Path, Path]:
    project_dir = home / ".sase" / "projects" / "myproj"
    artifacts_dir = project_dir / "artifacts" / "ace-run" / "20260510130000"
    artifacts_dir.mkdir(parents=True)
    project_file = project_dir / "myproj.sase"
    project_file.write_text(
        "# Test Project\n\n"
        "RUNNING:\n"
        "  #1 | 22222 | run | feature_x | 20260510130000\n"
        "\n"
        "NAME: feature_x\n"
        "DESCRIPTION:\n"
        "  Test\n"
        "PARENT: None\n"
        "CL: None\n"
        "STATUS: Ready\n"
    )
    return artifacts_dir, project_file


def _patch_home(home: Path) -> AbstractContextManager[object]:
    return patch("pathlib.Path.home", return_value=home)


def test_kill_named_agent_writes_dismissal_for_nonhome_uses_claim_cl_name(
    tmp_path: Path,
) -> None:
    artifacts_dir, _ = _setup_nonhome_agent(tmp_path)
    found = NamedAgent(
        name="my_agent",
        artifacts_dir=str(artifacts_dir),
        is_done=False,
        outcome=None,
    )

    with (
        _patch_home(tmp_path),
        patch("sase.agent.running.find_named_agent", return_value=found),
        patch("sase.agent.running.os.killpg"),
        patch("sase.running_field.release_workspace"),
        patch("sase.agent.running.sync_dismissed_agent_artifact_index") as sync_index,
    ):
        result = kill_named_agent("my_agent")

    assert result.success is True

    from sase.ace.dismissed_agents import load_dismissed_agents
    from sase.ace.tui.models.agent import AgentType

    dismissed = load_dismissed_agents()
    identity = (AgentType.RUNNING, "feature_x", "20260510130000")
    assert identity in dismissed
    sync_index.assert_called_once_with(dismissed, added={identity})


def test_kill_named_agent_writes_dismissal_for_home_uses_meta_cl_name(
    tmp_path: Path,
) -> None:
    artifacts_dir = _setup_home_agent(tmp_path, with_cl_name=True)
    found = NamedAgent(
        name="home_agent",
        artifacts_dir=str(artifacts_dir),
        is_done=False,
        outcome=None,
    )

    with (
        _patch_home(tmp_path),
        patch("sase.agent.running.find_named_agent", return_value=found),
        patch("sase.agent.running.os.killpg"),
        patch(
            "sase.agent.running.update_agent_artifact_index_for_marker_mutation"
        ) as update_index,
    ):
        result = kill_named_agent("home_agent")

    assert result.success is True
    update_index.assert_called_once_with(artifacts_dir)

    from sase.ace.dismissed_agents import load_dismissed_agents
    from sase.ace.tui.models.agent import AgentType

    dismissed = load_dismissed_agents()
    assert (AgentType.RUNNING, "home_feature", "20260510120000") in dismissed


def test_kill_named_agent_falls_back_to_unknown_cl_name_for_home_without_meta(
    tmp_path: Path,
) -> None:
    artifacts_dir = _setup_home_agent(tmp_path, with_cl_name=False)
    found = NamedAgent(
        name="home_agent",
        artifacts_dir=str(artifacts_dir),
        is_done=False,
        outcome=None,
    )

    with (
        _patch_home(tmp_path),
        patch("sase.agent.running.find_named_agent", return_value=found),
        patch("sase.agent.running.os.killpg"),
    ):
        result = kill_named_agent("home_agent")

    assert result.success is True

    from sase.ace.dismissed_agents import load_dismissed_agents
    from sase.ace.tui.models.agent import AgentType

    dismissed = load_dismissed_agents()
    assert (AgentType.RUNNING, "unknown", "20260510120000") in dismissed


def test_kill_named_agent_writes_dismissal_when_process_already_stopped(
    tmp_path: Path,
) -> None:
    artifacts_dir, _ = _setup_nonhome_agent(tmp_path)
    found = NamedAgent(
        name="my_agent",
        artifacts_dir=str(artifacts_dir),
        is_done=False,
        outcome=None,
    )

    with (
        _patch_home(tmp_path),
        patch("sase.agent.running.find_named_agent", return_value=found),
        patch("sase.agent.running.os.killpg", side_effect=ProcessLookupError),
        patch("sase.running_field.release_workspace"),
    ):
        result = kill_named_agent("my_agent")

    assert result.success is True
    assert result.status == "already_stopped"

    from sase.ace.dismissed_agents import load_dismissed_agents
    from sase.ace.tui.models.agent import AgentType

    assert (AgentType.RUNNING, "feature_x", "20260510130000") in load_dismissed_agents()


def test_kill_named_agent_index_write_failure_does_not_flip_success(
    tmp_path: Path,
) -> None:
    artifacts_dir, _ = _setup_nonhome_agent(tmp_path)
    found = NamedAgent(
        name="my_agent",
        artifacts_dir=str(artifacts_dir),
        is_done=False,
        outcome=None,
    )

    with (
        _patch_home(tmp_path),
        patch("sase.agent.running.find_named_agent", return_value=found),
        patch("sase.agent.running.os.killpg"),
        patch("sase.running_field.release_workspace"),
        patch(
            "sase.ace.dismissed_agents.save_dismissed_agents",
            side_effect=RuntimeError("disk full"),
        ),
    ):
        result = kill_named_agent("my_agent")

    assert result.success is True


def test_kill_named_agent_does_not_write_dismissal_when_pid_missing(
    tmp_path: Path,
    _isolated_dismissed_index: Path,
) -> None:
    """Kill that fails before signalling shouldn't dismiss."""
    project_dir = tmp_path / ".sase" / "projects" / "myproj"
    artifacts_dir = project_dir / "artifacts" / "ace-run" / "20260510140000"
    artifacts_dir.mkdir(parents=True)
    project_file = project_dir / "myproj.sase"
    project_file.write_text("# Test Project\n\nNAME: feature_x\nSTATUS: Wip\n")

    found = NamedAgent(
        name="my_agent",
        artifacts_dir=str(artifacts_dir),
        is_done=False,
        outcome=None,
    )

    with (
        _patch_home(tmp_path),
        patch("sase.agent.running.find_named_agent", return_value=found),
    ):
        result = kill_named_agent("my_agent")

    assert result.success is False
    assert result.reason == "missing_pid"
    assert not _isolated_dismissed_index.exists()


@pytest.mark.parametrize("home_or_nonhome", ["home", "nonhome"])
def test_kill_named_agent_dismissal_is_idempotent(
    tmp_path: Path, home_or_nonhome: str
) -> None:
    if home_or_nonhome == "home":
        artifacts_dir = _setup_home_agent(tmp_path, with_cl_name=True)
        ts = "20260510120000"
        cl_name = "home_feature"
    else:
        artifacts_dir, _ = _setup_nonhome_agent(tmp_path)
        ts = "20260510130000"
        cl_name = "feature_x"

    found = NamedAgent(
        name="agent",
        artifacts_dir=str(artifacts_dir),
        is_done=False,
        outcome=None,
    )

    with (
        _patch_home(tmp_path),
        patch("sase.agent.running.find_named_agent", return_value=found),
        patch("sase.agent.running.os.killpg"),
        patch("sase.running_field.release_workspace"),
    ):
        kill_named_agent("agent")
        kill_named_agent("agent")

    from sase.ace.dismissed_agents import load_dismissed_agents
    from sase.ace.tui.models.agent import AgentType

    dismissed = load_dismissed_agents()
    matching = [
        ident for ident in dismissed if ident == (AgentType.RUNNING, cl_name, ts)
    ]
    assert len(matching) == 1
