"""Tests for agent tag persistence and helpers."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from sase.ace.agent_tags import (
    InvalidTagError,
    add_tags,
    load_agent_tags,
    remove_tags,
    save_agent_tags,
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
        tags: dict[tuple[AgentType, str, str | None], tuple[str, ...]] = {
            (AgentType.RUNNING, "fix-bug", "20260425010000"): ("release-blockers",),
            (AgentType.WORKFLOW, "ship-feature", "20260425020000"): (
                "experiments",
                "release-blockers",
            ),
        }
        assert save_agent_tags(tags)
        # The on-disk file is real JSON we can inspect.
        data = json.loads(test_file.read_text())
        assert isinstance(data, list)
        assert len(data) == 2
        result = load_agent_tags()
        assert result == tags


def test_save_drops_empty_tag_lists(tmp_path: Path) -> None:
    test_file = tmp_path / "agent_tags.json"
    with patch("sase.ace.agent_tags._AGENT_TAGS_FILE", test_file):
        tags: dict[tuple[AgentType, str, str | None], tuple[str, ...]] = {
            (AgentType.RUNNING, "a", "20260425010000"): (),
            (AgentType.RUNNING, "b", "20260425020000"): ("keep",),
        }
        assert save_agent_tags(tags)
        result = load_agent_tags()
        assert result == {(AgentType.RUNNING, "b", "20260425020000"): ("keep",)}


def test_null_raw_suffix_round_trip(tmp_path: Path) -> None:
    test_file = tmp_path / "agent_tags.json"
    with patch("sase.ace.agent_tags._AGENT_TAGS_FILE", test_file):
        tags: dict[tuple[AgentType, str, str | None], tuple[str, ...]] = {
            (AgentType.RUNNING, "anon", None): ("ad-hoc",)
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
                {"id": ["run", "ok", "ts1"], "tags": ["good", "bad tag", "good"]},
                {"id": ["unknown_type", "bad", "ts"], "tags": ["x"]},
                {"id": ["run", 42, "ts"], "tags": ["x"]},
                {"id": ["run", "no-tags", "ts2"], "tags": []},
                {"id": ["run", "missing-tag-list", "ts3"]},
                "garbage",
            ]
        )
    )
    with patch("sase.ace.agent_tags._AGENT_TAGS_FILE", test_file):
        # Only the first entry is salvageable: duplicate "good" collapsed,
        # invalid "bad tag" filtered out.
        assert load_agent_tags() == {
            (AgentType.RUNNING, "ok", "ts1"): ("good",),
        }


def test_validate_tag_name_rejects_at_prefix() -> None:
    with pytest.raises(InvalidTagError, match="must not start with '@'"):
        validate_tag_name("@release")


def test_validate_tag_name_rejects_invalid_chars() -> None:
    with pytest.raises(InvalidTagError, match="must match"):
        validate_tag_name("has space")


def test_validate_tag_name_rejects_empty() -> None:
    with pytest.raises(InvalidTagError):
        validate_tag_name("")


def test_validate_tag_name_accepts_allowed_chars() -> None:
    assert validate_tag_name("Release-Blocker_42") == "Release-Blocker_42"


def test_add_tags_preserves_order_and_dedups() -> None:
    store: dict[tuple[AgentType, str, str | None], tuple[str, ...]] = {}
    identity = (AgentType.RUNNING, "cl", "ts")
    add_tags(store, identity, ["alpha", "beta"])
    add_tags(store, identity, ["beta", "gamma"])
    assert store[identity] == ("alpha", "beta", "gamma")


def test_add_tags_validates_inputs() -> None:
    store: dict[tuple[AgentType, str, str | None], tuple[str, ...]] = {}
    identity = (AgentType.RUNNING, "cl", "ts")
    with pytest.raises(InvalidTagError):
        add_tags(store, identity, ["@bad"])
    assert store == {}


def test_remove_tags_drops_empty_identity() -> None:
    identity = (AgentType.RUNNING, "cl", "ts")
    store: dict[tuple[AgentType, str, str | None], tuple[str, ...]] = {
        identity: ("a", "b"),
    }
    remove_tags(store, identity, ["a", "b"])
    assert identity not in store


def test_remove_tags_keeps_others() -> None:
    identity = (AgentType.RUNNING, "cl", "ts")
    store: dict[tuple[AgentType, str, str | None], tuple[str, ...]] = {
        identity: ("a", "b", "c"),
    }
    remaining = remove_tags(store, identity, ["b"])
    assert remaining == ("a", "c")
    assert store[identity] == ("a", "c")


def test_save_atomic_replace_overwrites_existing_file(tmp_path: Path) -> None:
    test_file = tmp_path / "agent_tags.json"
    test_file.write_text("stale contents")
    with patch("sase.ace.agent_tags._AGENT_TAGS_FILE", test_file):
        save_agent_tags(
            {(AgentType.RUNNING, "x", "ts"): ("fresh",)},
        )
        assert json.loads(test_file.read_text()) == [
            {"id": ["run", "x", "ts"], "tags": ["fresh"]}
        ]
