"""Tests for resolve_wait_chat_paths helper."""

import json
from pathlib import Path
from unittest.mock import patch

from sase.agent.names import NamedAgent
from sase.axe.run_agent_phases import resolve_wait_chat_paths
from tests._agent_names_fixtures import make_agent


def _seed_done(tmp_path: Path, name: str, response_path: str | None) -> NamedAgent:
    artifact_dir = tmp_path / name
    artifact_dir.mkdir()
    done: dict[str, object] = {"outcome": "completed"}
    if response_path is not None:
        done["response_path"] = response_path
    with open(artifact_dir / "done.json", "w", encoding="utf-8") as f:
        json.dump(done, f)
    return NamedAgent(
        name=name,
        artifacts_dir=str(artifact_dir),
        is_done=True,
        outcome="completed",
    )


def test_resolve_wait_chat_paths_single_name(tmp_path: Path) -> None:
    agent = _seed_done(tmp_path, "a", "~/.sase/chats/a.md")

    with patch(
        "sase.agent.names.resolve_resume_agent_name",
        return_value=agent,
    ):
        assert resolve_wait_chat_paths(["a"]) == ["~/.sase/chats/a.md"]


def test_resolve_wait_chat_paths_preserves_order(tmp_path: Path) -> None:
    agent_a = _seed_done(tmp_path, "a", "~/.sase/chats/a.md")
    agent_b = _seed_done(tmp_path, "b", "~/.sase/chats/b.md")
    lookup = {"a": agent_a, "b": agent_b}

    with patch(
        "sase.agent.names.resolve_resume_agent_name",
        side_effect=lambda name, **_kw: lookup.get(name),
    ):
        assert resolve_wait_chat_paths(["b", "a"]) == [
            "~/.sase/chats/b.md",
            "~/.sase/chats/a.md",
        ]


def test_resolve_wait_chat_paths_preserves_duplicates(tmp_path: Path) -> None:
    agent = _seed_done(tmp_path, "a", "~/.sase/chats/a.md")

    with patch(
        "sase.agent.names.resolve_resume_agent_name",
        return_value=agent,
    ):
        assert resolve_wait_chat_paths(["a", "a"]) == [
            "~/.sase/chats/a.md",
            "~/.sase/chats/a.md",
        ]


def test_resolve_wait_chat_paths_skips_unresolvable_name(tmp_path: Path) -> None:
    agent = _seed_done(tmp_path, "a", "~/.sase/chats/a.md")
    lookup = {"a": agent}

    with patch(
        "sase.agent.names.resolve_resume_agent_name",
        side_effect=lambda name, **_kw: lookup.get(name),
    ):
        # "missing" has no agent — should be skipped, not raise
        assert resolve_wait_chat_paths(["a", "missing"]) == [
            "~/.sase/chats/a.md",
        ]


def test_resolve_wait_chat_paths_skips_agent_without_response_path(
    tmp_path: Path,
) -> None:
    agent_ok = _seed_done(tmp_path, "a", "~/.sase/chats/a.md")
    agent_no_resp = _seed_done(tmp_path, "b", None)
    lookup = {"a": agent_ok, "b": agent_no_resp}

    with patch(
        "sase.agent.names.resolve_resume_agent_name",
        side_effect=lambda name, **_kw: lookup.get(name),
    ):
        assert resolve_wait_chat_paths(["a", "b"]) == ["~/.sase/chats/a.md"]


def test_resolve_wait_chat_paths_uses_latest_completed_family_member(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    make_agent(
        tmp_path,
        "proj",
        "20260506010101",
        "family",
        workflow_name="family",
        agent_family="family",
        role_suffix="-plan",
        done=True,
        outcome="completed",
        response_path="~/.sase/chats/family-plan.md",
    )
    make_agent(
        tmp_path,
        "proj",
        "20260506010202",
        "family-code",
        workflow_name="family",
        agent_family="family",
        role_suffix="-code",
        parent_timestamp="20260506010101",
        done=True,
        outcome="completed",
        response_path="~/.sase/chats/family-code.md",
    )

    assert resolve_wait_chat_paths(["family"]) == ["~/.sase/chats/family-code.md"]
