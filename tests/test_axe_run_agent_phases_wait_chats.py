"""Tests for resolve_wait_chat_paths helper."""

import json
from pathlib import Path
from unittest.mock import patch

from sase.agent.names import NamedAgent
from sase.axe.run_agent_phases import (
    WaitRuntimeNamespace,
    resolve_wait_chat_paths,
    resolve_wait_context,
)
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


def test_resolve_wait_chat_paths_resolves_indexed_template(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    make_agent(
        tmp_path,
        "proj",
        "20260506010101",
        "build-1",
        done=True,
        outcome="completed",
        response_path="~/.sase/chats/build-1.md",
    )
    make_agent(
        tmp_path,
        "proj",
        "20260506010202",
        "build-4",
        done=True,
        outcome="completed",
        response_path="~/.sase/chats/build-4.md",
    )

    assert resolve_wait_chat_paths(["build-@"]) == ["~/.sase/chats/build-4.md"]


def test_resolve_wait_context_keeps_artifact_producer_without_chat(
    tmp_path: Path,
) -> None:
    agent = _seed_done(tmp_path, "a", None)

    with patch(
        "sase.agent.names.resolve_resume_agent_name",
        return_value=agent,
    ):
        context = resolve_wait_context(["a"])

    assert context.chats == []
    [entry] = context.entries
    assert entry.wait_name == "a"
    assert entry.agent_artifacts_dirs == (str(Path(agent.artifacts_dir).resolve()),)


def test_wait_runtime_namespace_queries_artifacts_once(
    tmp_path: Path,
    monkeypatch,
) -> None:
    agent = _seed_done(tmp_path, "a", "~/.sase/chats/a.md")
    calls: list[object] = []

    with patch(
        "sase.agent.names.resolve_resume_agent_name",
        return_value=agent,
    ):
        context = resolve_wait_context(["a"])

    def fake_query(groups: object) -> list[dict[str, object]]:
        calls.append(groups)
        return [{"wait_name": "a", "ref": "file:report"}]

    monkeypatch.setattr(
        "sase.core.artifact_context_query_facade.query_artifact_context",
        fake_query,
    )
    namespace = WaitRuntimeNamespace(context)

    assert namespace.chats == ["~/.sase/chats/a.md"]
    assert namespace.artifacts == [{"wait_name": "a", "ref": "file:report"}]
    assert namespace.artifacts == [{"wait_name": "a", "ref": "file:report"}]
    assert len(calls) == 1


def test_wait_runtime_namespace_empty_context_does_not_query(
    monkeypatch,
) -> None:
    def fail_query(_groups: object) -> list[dict[str, object]]:
        raise AssertionError("artifact query should not run")

    monkeypatch.setattr(
        "sase.core.artifact_context_query_facade.query_artifact_context",
        fail_query,
    )

    assert WaitRuntimeNamespace(resolve_wait_context([])).artifacts == []
