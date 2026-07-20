"""Tests for agent-clan chat resolution."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from sase.scripts.agent_chat_from_name import _resolve_agent_chat_sources, main
from tests._agent_chat_from_name_helpers import write_agent


def test_complete_clan_emits_all_members_in_launch_order(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    older_chat = tmp_path / "older.md"
    newer_chat = tmp_path / "newer.md"
    older_dir = write_agent(
        tmp_path,
        "20260718010101",
        "review.alpha",
        done={"response_path": str(older_chat), "outcome": "completed"},
        meta={
            "agent_clan": "review",
            "agent_clan_generation": "20260718010000",
            "clan_tribe": "epic",
        },
    )
    newer_dir = write_agent(
        tmp_path,
        "20260718010202",
        "review.beta",
        done={"response_path": str(newer_chat), "outcome": "completed"},
        meta={
            "agent_clan": "review",
            "agent_clan_generation": "20260718010000",
            "clan_tribe": "epic",
        },
    )

    assert main(["review"]) == 0
    output = json.loads(capsys.readouterr().out)
    assert output["path"] == str(newer_chat)
    assert json.loads(output["sources_json"]) == [
        {
            "kind": "clan",
            "name": "review",
            "generation": "20260718010000",
            "tribe": "epic",
            "members": [
                {
                    "name": "review.alpha",
                    "path": str(older_chat),
                    "artifact_dir": str(older_dir),
                },
                {
                    "name": "review.beta",
                    "path": str(newer_chat),
                    "artifact_dir": str(newer_dir),
                },
            ],
        }
    ]


def test_incomplete_clan_is_rejected_as_a_fork_parent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    chat = tmp_path / "complete.md"
    for suffix, name, done in (
        (
            "20260718010101",
            "review.alpha",
            {"response_path": str(chat), "outcome": "completed"},
        ),
        ("20260718010202", "review.beta", None),
    ):
        write_agent(
            tmp_path,
            suffix,
            name,
            done=done,
            meta={
                "agent_clan": "review",
                "agent_clan_generation": "20260718010000",
            },
        )

    with pytest.raises(RuntimeError, match="No agent with chat history found"):
        _resolve_agent_chat_sources(["review"])


def test_clan_and_agent_sources_preserve_parent_order(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    clan_chat = tmp_path / "clan.md"
    agent_chat = tmp_path / "agent.md"
    write_agent(
        tmp_path,
        "20260718010101",
        "review.alpha",
        done={"response_path": str(clan_chat), "outcome": "completed"},
        meta={
            "agent_clan": "review",
            "agent_clan_generation": "20260718010000",
        },
    )
    write_agent(
        tmp_path,
        "20260718020202",
        "builder",
        done={"response_path": str(agent_chat), "outcome": "completed"},
    )

    sources = _resolve_agent_chat_sources(["review", "builder"])

    assert [(source.kind, source.name) for source in sources] == [
        ("clan", "review"),
        ("agent", "builder"),
    ]
