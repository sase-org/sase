"""Tests for agent-clan chat resolution."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from sase.scripts.agent_chat_from_name import _resolve_agent_chat_sources, main
from tests._agent_chat_from_name_helpers import write_agent
from tests._dismissed_completion_helpers import (
    add_archive_identity,
    rebuild_completion_archive,
    write_dismissed_completion,
)


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

    with pytest.raises(
        RuntimeError,
        match=r"Clan 'review' is not complete: 1/2 members done",
    ):
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


def test_clan_fork_includes_live_and_dismissed_member_transcripts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    generation = "20260720160000"
    archived_chat = tmp_path / "archived.md"
    live_chat = tmp_path / "live.md"
    archived_dir = write_agent(
        tmp_path,
        "20260720160100",
        "review.archived",
        done={"response_path": str(archived_chat), "outcome": "completed"},
        meta={
            "agent_clan": "review",
            "agent_clan_generation": generation,
            "changespec_name": "change",
        },
    )
    add_archive_identity(archived_dir)
    write_dismissed_completion(
        tmp_path,
        archived_dir,
        "review.archived",
        response_path=str(archived_chat),
    )
    (archived_dir / "done.json").unlink()
    live_dir = write_agent(
        tmp_path,
        "20260720160200",
        "review.live",
        done={"response_path": str(live_chat), "outcome": "completed"},
        meta={
            "agent_clan": "review",
            "agent_clan_generation": generation,
        },
    )
    rebuild_completion_archive()

    source = _resolve_agent_chat_sources(["review"])[0]

    assert source.path == str(live_chat)
    assert [
        (member.name, member.path, member.artifact_dir) for member in source.members
    ] == [
        ("review.archived", str(archived_chat), str(archived_dir)),
        ("review.live", str(live_chat), str(live_dir)),
    ]


def test_clan_fork_recovers_dismissed_member_from_day_sharded_artifacts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    timestamp = "20260720160300"
    archived_chat = tmp_path / "archived-sharded.md"
    legacy_dir = write_agent(
        tmp_path,
        timestamp,
        "review.archived",
        done={"response_path": str(archived_chat), "outcome": "completed"},
        meta={
            "agent_clan": "review",
            "agent_clan_generation": "20260720160000",
            "changespec_name": "change",
        },
    )
    archived_dir = legacy_dir.parent / timestamp[:6] / timestamp[6:8] / timestamp
    archived_dir.parent.mkdir(parents=True)
    legacy_dir.rename(archived_dir)
    add_archive_identity(archived_dir)
    write_dismissed_completion(
        tmp_path,
        archived_dir,
        "review.archived",
        project_name="proj",
        response_path=str(archived_chat),
    )
    (archived_dir / "done.json").unlink()
    rebuild_completion_archive()

    source = _resolve_agent_chat_sources(["review"])[0]

    assert source.members[0].path == str(archived_chat)
    assert source.members[0].artifact_dir == str(archived_dir)


def test_archived_failed_clan_member_keeps_fork_incomplete(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    generation = "20260720170000"
    failed = write_agent(
        tmp_path,
        "20260720170100",
        "review.failed",
        meta={
            "agent_clan": "review",
            "agent_clan_generation": generation,
            "changespec_name": "change",
        },
    )
    add_archive_identity(failed)
    write_dismissed_completion(
        tmp_path,
        failed,
        "review.failed",
        status="FAILED",
    )
    write_agent(
        tmp_path,
        "20260720170200",
        "review.live",
        done={
            "response_path": str(tmp_path / "live.md"),
            "outcome": "completed",
        },
        meta={
            "agent_clan": "review",
            "agent_clan_generation": generation,
        },
    )
    rebuild_completion_archive()

    with pytest.raises(
        RuntimeError,
        match=r"Clan 'review' is not complete: 1/2 members done",
    ):
        _resolve_agent_chat_sources(["review"])


def test_unreadable_archived_clan_transcript_fails_explicitly(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    transcript = tmp_path / "missing.md"
    artifact_dir = write_agent(
        tmp_path,
        "20260720180100",
        "review.archived",
        meta={
            "agent_clan": "review",
            "agent_clan_generation": "20260720180000",
            "changespec_name": "change",
        },
    )
    add_archive_identity(artifact_dir)
    write_dismissed_completion(
        tmp_path,
        artifact_dir,
        "review.archived",
        response_path=str(transcript),
    )
    rebuild_completion_archive()

    with pytest.raises(
        RuntimeError,
        match=r"Transcript for agent 'review\.archived' is not readable",
    ):
        _resolve_agent_chat_sources(["review"])
