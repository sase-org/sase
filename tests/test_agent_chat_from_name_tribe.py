"""Tests for agent-tribe chat resolution."""

from __future__ import annotations

from pathlib import Path

import pytest

from sase.scripts.agent_chat_from_name import _resolve_agent_chat_sources
from tests._agent_chat_from_name_helpers import write_agent
from tests._dismissed_completion_helpers import (
    add_archive_identity,
    rebuild_completion_archive,
    write_dismissed_completion,
)


def test_tribe_fork_resolves_earliest_complete_standalone_agent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    current_dir = write_agent(tmp_path, "20260718020000", "waiter")
    write_agent(
        tmp_path,
        "20260718010000",
        "old",
        done={
            "response_path": str(tmp_path / "old.md"),
            "outcome": "completed",
        },
        meta={"tribe": "epic"},
    )
    earliest_chat = tmp_path / "earliest.md"
    write_agent(
        tmp_path,
        "20260718022000",
        "earliest",
        done={"response_path": str(earliest_chat), "outcome": "completed"},
        meta={"tribe": "epic"},
    )
    write_agent(
        tmp_path,
        "20260718024000",
        "later",
        done={
            "response_path": str(tmp_path / "later.md"),
            "outcome": "completed",
        },
        meta={"tribe": "epic"},
    )
    monkeypatch.setenv("SASE_ARTIFACTS_DIR", str(current_dir))

    sources = _resolve_agent_chat_sources(["@epic"])

    assert [(source.kind, source.name, source.path) for source in sources] == [
        ("agent", "earliest", str(earliest_chat))
    ]


def test_tribe_fork_dispatches_complete_clan_to_clan_source(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    current_dir = write_agent(tmp_path, "20260718020000", "waiter")
    generation = "20260718021000"
    first_chat = tmp_path / "first.md"
    second_chat = tmp_path / "second.md"
    first_dir = write_agent(
        tmp_path,
        "20260718022000",
        "review.one",
        done={"response_path": str(first_chat), "outcome": "completed"},
        meta={
            "agent_clan": "review",
            "agent_clan_generation": generation,
            "clan_tribe": "epic",
        },
    )
    second_dir = write_agent(
        tmp_path,
        "20260718023000",
        "review.two",
        done={"response_path": str(second_chat), "outcome": "completed"},
        meta={
            "agent_clan": "review",
            "agent_clan_generation": generation,
            "clan_tribe": "epic",
        },
    )
    monkeypatch.setenv("SASE_ARTIFACTS_DIR", str(current_dir))

    source = _resolve_agent_chat_sources(["@epic"])[0]

    assert source.kind == "clan"
    assert source.name == "review"
    assert source.generation == generation
    assert source.tribe == "epic"
    assert source.path == str(second_chat)
    assert [
        (member.name, member.path, member.artifact_dir) for member in source.members
    ] == [
        ("review.one", str(first_chat), str(first_dir)),
        ("review.two", str(second_chat), str(second_dir)),
    ]


def test_tribe_fork_requires_launch_cutoff(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))

    with pytest.raises(RuntimeError, match="SASE_ARTIFACTS_DIR is not set"):
        _resolve_agent_chat_sources(["@epic"])


def test_mixed_tribe_and_named_fork_parents_preserve_order(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    current_dir = write_agent(tmp_path, "20260718020000", "waiter")
    tribe_chat = tmp_path / "tribe.md"
    named_chat = tmp_path / "named.md"
    write_agent(
        tmp_path,
        "20260718022000",
        "tribe-worker",
        done={"response_path": str(tribe_chat), "outcome": "completed"},
        meta={"tribe": "epic"},
    )
    write_agent(
        tmp_path,
        "20260718023000",
        "builder",
        done={"response_path": str(named_chat), "outcome": "completed"},
    )
    monkeypatch.setenv("SASE_ARTIFACTS_DIR", str(current_dir))

    sources = _resolve_agent_chat_sources(["@epic", "builder"])

    assert [(source.kind, source.name) for source in sources] == [
        ("agent", "tribe-worker"),
        ("agent", "builder"),
    ]


def test_tribe_fork_reads_archived_clan_member_transcript(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    current_dir = write_agent(tmp_path, "20260720200000", "waiter")
    generation = "20260720201000"
    archived_chat = tmp_path / "archived.md"
    archived_dir = write_agent(
        tmp_path,
        "20260720202000",
        "review.archived",
        done={"response_path": str(archived_chat), "outcome": "completed"},
        meta={
            "agent_clan": "review",
            "agent_clan_generation": generation,
            "clan_tribe": "epic",
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
    live_chat = tmp_path / "live.md"
    write_agent(
        tmp_path,
        "20260720203000",
        "review.live",
        done={"response_path": str(live_chat), "outcome": "completed"},
        meta={
            "agent_clan": "review",
            "agent_clan_generation": generation,
        },
    )
    rebuild_completion_archive()
    monkeypatch.setenv("SASE_ARTIFACTS_DIR", str(current_dir))

    source = _resolve_agent_chat_sources(["@epic"])[0]

    assert source.kind == "clan"
    assert [(member.name, member.path) for member in source.members] == [
        ("review.archived", str(archived_chat)),
        ("review.live", str(live_chat)),
    ]


def test_tribe_fork_rejects_reserved_default_tribe(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The fork workflow explains the reserved panel rather than reporting a miss."""
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    current_dir = write_agent(tmp_path, "20260718020000", "waiter")
    monkeypatch.setenv("SASE_ARTIFACTS_DIR", str(current_dir))

    with pytest.raises(RuntimeError) as excinfo:
        _resolve_agent_chat_sources(["@default"])

    message = str(excinfo.value)
    assert "Invalid '#fork' tribe reference" in message
    assert "reserved @default panel" in message
