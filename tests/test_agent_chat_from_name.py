"""Tests for the ``agent_chat_from_name`` resume resolver."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from sase.scripts.agent_chat_from_name import (
    _resolve_agent_chat_path,
    _resolve_agent_chat_sources,
    main,
)


def _write_agent(
    home: Path,
    suffix: str,
    name: str,
    *,
    done: dict[str, object] | None = None,
    meta: dict[str, object] | None = None,
    malformed_meta: bool = False,
) -> Path:
    artifacts_dir = (
        home / ".sase" / "projects" / "proj" / "artifacts" / "ace-run" / suffix
    )
    artifacts_dir.mkdir(parents=True)
    if malformed_meta:
        (artifacts_dir / "agent_meta.json").write_text("{", encoding="utf-8")
    else:
        meta_data: dict[str, object] = {"name": name}
        if meta:
            meta_data.update(meta)
        (artifacts_dir / "agent_meta.json").write_text(
            json.dumps(meta_data), encoding="utf-8"
        )
    if done is not None:
        (artifacts_dir / "done.json").write_text(json.dumps(done), encoding="utf-8")
    for data, field in ((done, "response_path"), (meta, "chat_path")):
        value = data.get(field) if data else None
        if isinstance(value, str):
            transcript = Path(value).expanduser()
            transcript.parent.mkdir(parents=True, exist_ok=True)
            transcript.write_text(f"transcript for {name}", encoding="utf-8")
    return artifacts_dir


def test_explicit_completed_agent_uses_done_response_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    chat = tmp_path / "done-chat.md"
    fallback = tmp_path / "meta-chat.md"
    _write_agent(
        tmp_path,
        "20260504010101",
        "alpha",
        done={"response_path": str(chat), "outcome": "completed"},
        meta={"chat_path": str(fallback)},
    )

    assert _resolve_agent_chat_path("alpha") == str(chat)


def test_agent_name_template_resolves_latest_completed_agent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    older_chat = tmp_path / "older-chat.md"
    newer_chat = tmp_path / "newer-chat.md"
    _write_agent(
        tmp_path,
        "20260504010101",
        "build-1",
        done={"response_path": str(older_chat), "outcome": "completed"},
    )
    _write_agent(
        tmp_path,
        "20260504020202",
        "build-3",
        done={"response_path": str(newer_chat), "outcome": "completed"},
    )

    assert _resolve_agent_chat_path("build-@") == str(newer_chat)


def test_agent_name_template_suffix_shape_resolves_latest_completed_agent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    older_chat = tmp_path / "older-chat.md"
    newer_chat = tmp_path / "newer-chat.md"
    _write_agent(
        tmp_path,
        "20260504010101",
        "cld.0",
        done={"response_path": str(older_chat), "outcome": "completed"},
    )
    _write_agent(
        tmp_path,
        "20260504020202",
        "cld.1",
        done={"response_path": str(newer_chat), "outcome": "completed"},
    )

    assert _resolve_agent_chat_path("cld.@") == str(newer_chat)


def test_agent_name_template_excludes_current_agent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    previous_chat = tmp_path / "previous-chat.md"
    _write_agent(
        tmp_path,
        "20260504010101",
        "build-1",
        done={"response_path": str(previous_chat), "outcome": "completed"},
    )
    current_dir = _write_agent(
        tmp_path,
        "20260504020202",
        "build-2",
        meta={"chat_path": str(tmp_path / "current-chat.md"), "pid": os.getpid()},
    )
    monkeypatch.setenv("SASE_ARTIFACTS_DIR", str(current_dir))

    assert _resolve_agent_chat_path("build-@") == str(previous_chat)


def test_explicit_running_agent_falls_back_to_meta_chat_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    chat = tmp_path / "running-chat.md"
    _write_agent(
        tmp_path,
        "20260504010101",
        "bravo",
        meta={"chat_path": str(chat), "pid": os.getpid()},
    )

    assert _resolve_agent_chat_path("bravo") == str(chat)


def test_family_name_forks_from_latest_completed_member(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    planner_chat = tmp_path / "planner.md"
    coder_chat = tmp_path / "coder.md"
    _write_agent(
        tmp_path,
        "20260718010101",
        "cx--plan",
        done={"response_path": str(planner_chat), "outcome": "completed"},
        meta={
            "workflow_name": "cx",
            "agent_family": "cx",
            "agent_family_role": "root",
            "role_suffix": "--plan",
        },
    )
    _write_agent(
        tmp_path,
        "20260718010202",
        "cx--code",
        done={"response_path": str(coder_chat), "outcome": "completed"},
        meta={
            "workflow_name": "cx",
            "agent_family": "cx",
            "agent_family_role": "code",
            "role_suffix": "--code",
            "parent_timestamp": "20260718010101",
        },
    )

    assert _resolve_agent_chat_path("cx") == str(coder_chat)
    assert _resolve_agent_chat_path("cx--plan") == str(planner_chat)


def test_family_source_includes_completed_members_in_chain_order(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    planner_chat = tmp_path / "planner.md"
    coder_chat = tmp_path / "coder.md"
    planner_dir = _write_agent(
        tmp_path,
        "20260718010101",
        "cx--plan",
        done={"response_path": str(planner_chat), "outcome": "completed"},
        meta={"agent_family": "cx"},
    )
    coder_dir = _write_agent(
        tmp_path,
        "20260718010202",
        "cx--code",
        done={"response_path": str(coder_chat), "outcome": "completed"},
        meta={"agent_family": "cx", "parent_timestamp": "20260718010101"},
    )

    source = _resolve_agent_chat_sources(["cx"])[0]
    explicit_member = _resolve_agent_chat_sources(["cx--plan"])[0]

    assert source.kind == "family"
    assert source.name == "cx"
    assert source.path == str(coder_chat)
    assert source.to_json_data() == {
        "kind": "family",
        "name": "cx",
        "members": [
            {
                "name": "cx--plan",
                "path": str(planner_chat),
                "artifact_dir": str(planner_dir),
                "outcome": "completed",
            },
            {
                "name": "cx--code",
                "path": str(coder_chat),
                "artifact_dir": str(coder_dir),
                "outcome": "completed",
            },
        ],
        "excluded": [],
    }
    assert explicit_member.kind == "agent"
    assert explicit_member.path == str(planner_chat)


def test_family_source_reports_running_tip_as_excluded(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    planner_chat = tmp_path / "planner.md"
    _write_agent(
        tmp_path,
        "20260718010101",
        "cx--plan",
        done={"response_path": str(planner_chat), "outcome": "completed"},
        meta={"agent_family": "cx"},
    )
    _write_agent(
        tmp_path,
        "20260718010202",
        "cx--code",
        meta={"agent_family": "cx", "parent_timestamp": "20260718010101"},
    )

    source = _resolve_agent_chat_sources(["cx"])[0]

    assert [member.name for member in source.members] == ["cx--plan"]
    assert [(member.name, member.status) for member in source.excluded] == [
        ("cx--code", "running")
    ]
    assert source.path == str(planner_chat)


def test_family_source_excludes_failed_and_unavailable_transcripts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    planner_chat = tmp_path / "planner.md"
    unreadable_chat = tmp_path / "unreadable.md"
    _write_agent(
        tmp_path,
        "20260718010101",
        "cx--plan",
        done={"response_path": str(planner_chat), "outcome": "completed"},
        meta={"agent_family": "cx"},
    )
    _write_agent(
        tmp_path,
        "20260718010202",
        "cx--code",
        done={"outcome": "completed"},
        meta={"agent_family": "cx", "parent_timestamp": "20260718010101"},
    )
    _write_agent(
        tmp_path,
        "20260718010303",
        "cx--test",
        done={"outcome": "failed"},
        meta={"agent_family": "cx", "parent_timestamp": "20260718010202"},
    )
    _write_agent(
        tmp_path,
        "20260718010404",
        "cx--fix",
        done={"response_path": str(unreadable_chat), "outcome": "completed"},
        meta={"agent_family": "cx", "parent_timestamp": "20260718010303"},
    )
    unreadable_chat.unlink()

    source = _resolve_agent_chat_sources(["cx"])[0]

    assert [member.name for member in source.members] == ["cx--plan"]
    assert [(member.name, member.status) for member in source.excluded] == [
        ("cx--code", "missing transcript"),
        ("cx--test", "failed"),
        ("cx--fix", "unreadable transcript"),
    ]


def test_family_source_requires_at_least_one_completed_transcript(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    _write_agent(
        tmp_path,
        "20260718010101",
        "cx--plan",
        meta={"agent_family": "cx"},
    )

    with pytest.raises(RuntimeError, match="No agent with chat history found for: cx"):
        _resolve_agent_chat_sources(["cx"])


def test_family_and_explicit_member_duplicate_transcript_are_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    planner_chat = tmp_path / "planner.md"
    coder_chat = tmp_path / "coder.md"
    _write_agent(
        tmp_path,
        "20260718010101",
        "cx--plan",
        done={"response_path": str(planner_chat), "outcome": "completed"},
        meta={"agent_family": "cx"},
    )
    _write_agent(
        tmp_path,
        "20260718010202",
        "cx--code",
        done={"response_path": str(coder_chat), "outcome": "completed"},
        meta={"agent_family": "cx", "parent_timestamp": "20260718010101"},
    )

    with pytest.raises(RuntimeError, match="same transcript"):
        _resolve_agent_chat_sources(["cx", "cx--code"])


def test_legacy_rootless_family_source_includes_all_completed_members(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    planner_chat = tmp_path / "planner.md"
    coder_chat = tmp_path / "coder.md"
    _write_agent(
        tmp_path,
        "20260718010101",
        "cx--plan",
        done={"response_path": str(planner_chat), "outcome": "completed"},
        meta={"agent_family": "cx", "parent_timestamp": "missing-root"},
    )
    _write_agent(
        tmp_path,
        "20260718010202",
        "cx--code",
        done={"response_path": str(coder_chat), "outcome": "completed"},
        meta={"agent_family": "cx", "parent_timestamp": "20260718010101"},
    )

    source = _resolve_agent_chat_sources(["cx"])[0]

    assert source.kind == "family"
    assert [member.name for member in source.members] == ["cx--plan", "cx--code"]
    assert source.path == str(coder_chat)


def test_missing_chat_history_fails_clearly(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    _write_agent(
        tmp_path,
        "20260504010101",
        "charlie",
        done={"outcome": "completed"},
    )

    with pytest.raises(
        RuntimeError, match="No agent with chat history found for: charlie"
    ):
        _resolve_agent_chat_path("charlie")


def test_malformed_metadata_is_ignored(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    _write_agent(tmp_path, "20260504010101", "bad", malformed_meta=True)

    with pytest.raises(RuntimeError, match="No agent with chat history found for: bad"):
        _resolve_agent_chat_path("bad")


def test_omitted_name_uses_most_recent_named_agent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    older_chat = tmp_path / "older.md"
    newer_chat = tmp_path / "newer.md"
    _write_agent(
        tmp_path,
        "20260504010101",
        "older",
        done={"response_path": str(older_chat), "outcome": "completed"},
    )
    _write_agent(
        tmp_path,
        "20260504020202",
        "newer",
        done={"response_path": str(newer_chat), "outcome": "completed"},
    )

    assert _resolve_agent_chat_path(None) == str(newer_chat)
    assert _resolve_agent_chat_path("") == str(newer_chat)


def test_omitted_name_excludes_current_artifacts_dir(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    older_chat = tmp_path / "older.md"
    _write_agent(
        tmp_path,
        "20260504010101",
        "older",
        done={"response_path": str(older_chat), "outcome": "completed"},
    )
    current_dir = _write_agent(
        tmp_path,
        "20260504020202",
        "current",
        done={"response_path": str(tmp_path / "current.md"), "outcome": "completed"},
    )
    monkeypatch.setenv("SASE_ARTIFACTS_DIR", str(current_dir))

    assert _resolve_agent_chat_path(None) == str(older_chat)


def test_omitted_name_fails_when_no_previous_named_agent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))

    with pytest.raises(RuntimeError, match="No previous named agent found"):
        _resolve_agent_chat_path(None)


def test_main_emits_parseable_json(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    chat = tmp_path / "chat.md"
    _write_agent(
        tmp_path,
        "20260504010101",
        "delta",
        done={"response_path": str(chat), "outcome": "completed"},
    )

    assert main(["delta"]) == 0
    output = json.loads(capsys.readouterr().out)
    assert output["path"] == str(chat)
    assert json.loads(output["sources_json"]) == [
        {"kind": "agent", "name": "delta", "path": str(chat)}
    ]


def test_multiple_agents_resolve_in_invocation_order(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    planner_chat = tmp_path / "planner.md"
    coder_chat = tmp_path / "coder.md"
    _write_agent(
        tmp_path,
        "20260504010101",
        "planner",
        done={"response_path": str(planner_chat), "outcome": "completed"},
    )
    _write_agent(
        tmp_path,
        "20260504020202",
        "coder",
        done={"response_path": str(coder_chat), "outcome": "completed"},
    )

    sources = _resolve_agent_chat_sources(["coder", "planner"])

    assert [(source.name, source.path) for source in sources] == [
        ("coder", str(coder_chat)),
        ("planner", str(planner_chat)),
    ]


def test_multiple_agents_report_all_invalid_parents_atomically(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    valid_chat = tmp_path / "valid.md"
    _write_agent(
        tmp_path,
        "20260504010101",
        "valid",
        done={"response_path": str(valid_chat), "outcome": "completed"},
    )

    with pytest.raises(RuntimeError) as exc_info:
        _resolve_agent_chat_sources(["missing-one", "valid", "missing-two"])

    message = str(exc_info.value)
    assert "missing-one" in message
    assert "missing-two" in message


def test_multiple_aliases_to_same_transcript_are_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    shared_chat = tmp_path / "shared.md"
    for index, name in enumerate(("planner", "planner-alias"), start=1):
        _write_agent(
            tmp_path,
            f"2026050401010{index}",
            name,
            done={"response_path": str(shared_chat), "outcome": "completed"},
        )

    with pytest.raises(RuntimeError, match="same transcript"):
        _resolve_agent_chat_sources(["planner", "planner-alias"])


def test_unreadable_transcript_is_rejected_before_loading(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    missing_chat = tmp_path / "missing.md"
    _write_agent(
        tmp_path,
        "20260504010101",
        "planner",
        done={"response_path": str(missing_chat), "outcome": "completed"},
    )
    missing_chat.unlink()

    with pytest.raises(RuntimeError, match="not readable"):
        _resolve_agent_chat_sources(["planner"])


def test_complete_clan_emits_all_members_in_launch_order(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    older_chat = tmp_path / "older.md"
    newer_chat = tmp_path / "newer.md"
    older_dir = _write_agent(
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
    newer_dir = _write_agent(
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
        _write_agent(
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
    _write_agent(
        tmp_path,
        "20260718010101",
        "review.alpha",
        done={"response_path": str(clan_chat), "outcome": "completed"},
        meta={
            "agent_clan": "review",
            "agent_clan_generation": "20260718010000",
        },
    )
    _write_agent(
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


def test_tribe_fork_resolves_earliest_complete_standalone_agent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    current_dir = _write_agent(tmp_path, "20260718020000", "waiter")
    _write_agent(
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
    _write_agent(
        tmp_path,
        "20260718022000",
        "earliest",
        done={"response_path": str(earliest_chat), "outcome": "completed"},
        meta={"tribe": "epic"},
    )
    _write_agent(
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
    current_dir = _write_agent(tmp_path, "20260718020000", "waiter")
    generation = "20260718021000"
    first_chat = tmp_path / "first.md"
    second_chat = tmp_path / "second.md"
    first_dir = _write_agent(
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
    second_dir = _write_agent(
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
    current_dir = _write_agent(tmp_path, "20260718020000", "waiter")
    tribe_chat = tmp_path / "tribe.md"
    named_chat = tmp_path / "named.md"
    _write_agent(
        tmp_path,
        "20260718022000",
        "tribe-worker",
        done={"response_path": str(tribe_chat), "outcome": "completed"},
        meta={"tribe": "epic"},
    )
    _write_agent(
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
