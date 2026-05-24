"""Tests for agent tag persistence and helpers."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from sase.ace.agent_tags import (
    InvalidTagError,
    load_agent_tags,
    save_agent_tags,
    set_tag,
    unset_tag,
    update_agent_tag,
    validate_tag_name,
)
from sase.ace.tui.models.agent import AgentType


def test_load_empty_when_no_file(tmp_path: Path) -> None:
    with patch(
        "sase.ace.agent_tags._AGENT_TAGS_FILE",
        tmp_path / "missing.json",
    ):
        assert load_agent_tags() == {}


def test_round_trip(tmp_path: Path) -> None:
    test_file = tmp_path / "agent_tags.json"
    with patch("sase.ace.agent_tags._AGENT_TAGS_FILE", test_file):
        tags: dict[tuple[AgentType, str, str | None], str] = {
            (AgentType.RUNNING, "fix-bug", "20260425010000"): "release-blockers",
            (AgentType.WORKFLOW, "ship-feature", "20260425020000"): "experiments",
        }
        assert save_agent_tags(tags)
        # The on-disk file is real JSON we can inspect.
        data = json.loads(test_file.read_text())
        assert isinstance(data, list)
        assert len(data) == 2
        result = load_agent_tags()
        assert result == tags


def test_save_drops_untagged_identities(tmp_path: Path) -> None:
    test_file = tmp_path / "agent_tags.json"
    with patch("sase.ace.agent_tags._AGENT_TAGS_FILE", test_file):
        tags: dict[tuple[AgentType, str, str | None], str] = {
            (AgentType.RUNNING, "a", "20260425010000"): "",  # type: ignore[dict-item]
            (AgentType.RUNNING, "b", "20260425020000"): "keep",
        }
        assert save_agent_tags(tags)
        result = load_agent_tags()
        assert result == {(AgentType.RUNNING, "b", "20260425020000"): "keep"}


def test_null_raw_suffix_round_trip(tmp_path: Path) -> None:
    test_file = tmp_path / "agent_tags.json"
    with patch("sase.ace.agent_tags._AGENT_TAGS_FILE", test_file):
        tags: dict[tuple[AgentType, str, str | None], str] = {
            (AgentType.RUNNING, "anon", None): "ad-hoc"
        }
        assert save_agent_tags(tags)
        assert load_agent_tags() == tags


def test_load_handles_corrupt_json(tmp_path: Path) -> None:
    test_file = tmp_path / "agent_tags.json"
    test_file.write_text("not valid json {")
    with patch("sase.ace.agent_tags._AGENT_TAGS_FILE", test_file):
        assert load_agent_tags() == {}


def test_load_handles_non_list_root(tmp_path: Path) -> None:
    test_file = tmp_path / "agent_tags.json"
    test_file.write_text('{"oops": "dict at root"}')
    with patch("sase.ace.agent_tags._AGENT_TAGS_FILE", test_file):
        assert load_agent_tags() == {}


def test_load_skips_malformed_entries(tmp_path: Path) -> None:
    test_file = tmp_path / "agent_tags.json"
    test_file.write_text(
        json.dumps(
            [
                {"id": ["run", "ok", "ts1"], "tag": "good"},
                {"id": ["unknown_type", "bad", "ts"], "tag": "x"},
                {"id": ["run", 42, "ts"], "tag": "x"},
                {"id": ["run", "bad-tag", "ts2"], "tag": "has space"},
                {"id": ["run", "missing-tag", "ts3"]},
                "garbage",
            ]
        )
    )
    with patch("sase.ace.agent_tags._AGENT_TAGS_FILE", test_file):
        assert load_agent_tags() == {
            (AgentType.RUNNING, "ok", "ts1"): "good",
        }


def test_load_migrates_legacy_multi_tag_entries(tmp_path: Path) -> None:
    """Legacy entries with ``"tags": [...]`` collapse to the first valid element."""
    test_file = tmp_path / "agent_tags.json"
    test_file.write_text(
        json.dumps(
            [
                {"id": ["run", "first-wins", "ts1"], "tags": ["alpha", "beta"]},
                {"id": ["workflow", "skip-bad", "ts2"], "tags": ["bad space", "ok"]},
                {"id": ["run", "all-bad", "ts3"], "tags": ["bad space", "@nope"]},
                {"id": ["run", "empty", "ts4"], "tags": []},
            ]
        )
    )
    with patch("sase.ace.agent_tags._AGENT_TAGS_FILE", test_file):
        assert load_agent_tags() == {
            (AgentType.RUNNING, "first-wins", "ts1"): "alpha",
            (AgentType.WORKFLOW, "skip-bad", "ts2"): "ok",
        }


def test_validate_tag_name_rejects_at_prefix() -> None:
    with pytest.raises(InvalidTagError, match="must not start with '@'"):
        validate_tag_name("@release")


def test_validate_tag_name_rejects_invalid_chars() -> None:
    with pytest.raises(InvalidTagError, match="must match"):
        validate_tag_name("has space")
    with pytest.raises(InvalidTagError, match="must match"):
        validate_tag_name("sase-42/3")


def test_validate_tag_name_rejects_empty() -> None:
    with pytest.raises(InvalidTagError):
        validate_tag_name("")


def test_validate_tag_name_accepts_allowed_chars() -> None:
    assert validate_tag_name("Release-Blocker_42") == "Release-Blocker_42"
    assert validate_tag_name("sase-42.3") == "sase-42.3"


def test_set_tag_replaces_previous_value() -> None:
    store: dict[tuple[AgentType, str, str | None], str] = {}
    identity = (AgentType.RUNNING, "cl", "ts")
    set_tag(store, identity, "alpha")
    set_tag(store, identity, "beta")
    assert store[identity] == "beta"


def test_set_tag_validates_input() -> None:
    store: dict[tuple[AgentType, str, str | None], str] = {}
    identity = (AgentType.RUNNING, "cl", "ts")
    with pytest.raises(InvalidTagError):
        set_tag(store, identity, "@bad")
    assert store == {}


def test_unset_tag_removes_identity() -> None:
    identity = (AgentType.RUNNING, "cl", "ts")
    store: dict[tuple[AgentType, str, str | None], str] = {identity: "a"}
    unset_tag(store, identity)
    assert identity not in store


def test_unset_tag_no_op_when_absent() -> None:
    store: dict[tuple[AgentType, str, str | None], str] = {}
    unset_tag(store, (AgentType.RUNNING, "cl", "ts"))
    assert store == {}


def test_save_atomic_replace_overwrites_existing_file(tmp_path: Path) -> None:
    test_file = tmp_path / "agent_tags.json"
    test_file.write_text("stale contents")
    with patch("sase.ace.agent_tags._AGENT_TAGS_FILE", test_file):
        save_agent_tags(
            {(AgentType.RUNNING, "x", "ts"): "fresh"},
        )
        assert json.loads(test_file.read_text()) == [
            {"id": ["run", "x", "ts"], "tag": "fresh"}
        ]


def test_update_agent_tag_preserves_existing_entries(tmp_path: Path) -> None:
    test_file = tmp_path / "agent_tags.json"
    existing = (AgentType.RUNNING, "keep", "ts1")
    new = (AgentType.WORKFLOW, "legend", "ts2")

    with patch("sase.ace.agent_tags._AGENT_TAGS_FILE", test_file):
        assert save_agent_tags({existing: "alpha"})
        assert update_agent_tag(new, "sase-26")

        assert load_agent_tags() == {
            existing: "alpha",
            new: "sase-26",
        }


def test_update_agent_tag_validates_input(tmp_path: Path) -> None:
    test_file = tmp_path / "agent_tags.json"
    identity = (AgentType.WORKFLOW, "legend", "ts")

    with patch("sase.ace.agent_tags._AGENT_TAGS_FILE", test_file):
        with pytest.raises(InvalidTagError):
            update_agent_tag(identity, "bad tag")
        assert load_agent_tags() == {}
