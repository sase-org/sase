"""Focused tests for canonical agent-tribe persistence helpers."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from sase.ace.agent_tribes import (
    InvalidTribeError,
    load_agent_tribes,
    save_agent_tribes,
    set_tribe,
    unset_tribe,
    update_agent_tribe,
    validate_tribe_name,
)
from sase.ace.tui.models.agent import AgentType


def _canonical_path(path: Path):  # type: ignore[no-untyped-def]
    return patch("sase.ace.agent_tribes._AGENT_TRIBES_FILE", path)


def test_load_empty_when_no_file(tmp_path: Path) -> None:
    with _canonical_path(tmp_path / "missing.json"):
        assert load_agent_tribes() == {}


def test_round_trip(tmp_path: Path) -> None:
    store_path = tmp_path / "agent_tribes.json"
    tribes = {
        (AgentType.RUNNING, "fix-bug", "20260425010000"): "release-blockers",
        (AgentType.WORKFLOW, "ship-feature", "20260425020000"): "experiments",
    }
    with _canonical_path(store_path):
        assert save_agent_tribes(tribes)
        assert load_agent_tribes() == tribes

    records = json.loads(store_path.read_text())
    assert all(set(record) == {"id", "tribe"} for record in records)


def test_save_drops_unassigned_identities(tmp_path: Path) -> None:
    store_path = tmp_path / "agent_tribes.json"
    tribes: dict[tuple[AgentType, str, str | None], str] = {
        (AgentType.RUNNING, "a", "20260425010000"): "",
        (AgentType.RUNNING, "b", "20260425020000"): "keep",
    }
    with _canonical_path(store_path):
        assert save_agent_tribes(tribes)
        assert load_agent_tribes() == {
            (AgentType.RUNNING, "b", "20260425020000"): "keep"
        }


def test_null_raw_suffix_round_trip(tmp_path: Path) -> None:
    store_path = tmp_path / "agent_tribes.json"
    tribes = {(AgentType.RUNNING, "anon", None): "ad-hoc"}
    with _canonical_path(store_path):
        assert save_agent_tribes(tribes)
        assert load_agent_tribes() == tribes


@pytest.mark.parametrize("payload", ["not valid json {", '{"oops": "dict"}'])
def test_load_handles_invalid_root(tmp_path: Path, payload: str) -> None:
    store_path = tmp_path / "agent_tribes.json"
    store_path.write_text(payload)
    with _canonical_path(store_path):
        assert load_agent_tribes() == {}


def test_load_skips_malformed_entries(tmp_path: Path) -> None:
    store_path = tmp_path / "agent_tribes.json"
    store_path.write_text(
        json.dumps(
            [
                {"id": ["run", "ok", "ts1"], "tribe": "good"},
                {"id": ["unknown_type", "bad", "ts"], "tribe": "x"},
                {"id": ["run", 42, "ts"], "tribe": "x"},
                {"id": ["run", "bad", "ts2"], "tribe": "has space"},
                {"id": ["run", "missing", "ts3"]},
                "garbage",
            ]
        )
    )
    with _canonical_path(store_path):
        assert load_agent_tribes() == {(AgentType.RUNNING, "ok", "ts1"): "good"}


@pytest.mark.parametrize("tribe", ["@release", "has space", "sase-42/3", ""])
def test_validate_tribe_name_rejects_invalid_values(tribe: str) -> None:
    with pytest.raises(InvalidTribeError):
        validate_tribe_name(tribe)


def test_validate_tribe_name_accepts_allowed_chars() -> None:
    assert validate_tribe_name("Release-Blocker_42") == "Release-Blocker_42"
    assert validate_tribe_name("sase-42.3") == "sase-42.3"


def test_set_and_unset_tribe() -> None:
    identity = (AgentType.RUNNING, "cl", "ts")
    store: dict[tuple[AgentType, str, str | None], str] = {}
    set_tribe(store, identity, "alpha")
    set_tribe(store, identity, "beta")
    assert store[identity] == "beta"
    unset_tribe(store, identity)
    assert identity not in store


def test_set_tribe_validates_input() -> None:
    store: dict[tuple[AgentType, str, str | None], str] = {}
    identity = (AgentType.RUNNING, "cl", "ts")
    with pytest.raises(InvalidTribeError):
        set_tribe(store, identity, "@bad")
    assert store == {}


def test_update_agent_tribe_preserves_existing_entries(tmp_path: Path) -> None:
    store_path = tmp_path / "agent_tribes.json"
    existing = (AgentType.RUNNING, "keep", "ts1")
    new = (AgentType.WORKFLOW, "sample", "ts2")
    with _canonical_path(store_path):
        assert save_agent_tribes({existing: "alpha"})
        assert update_agent_tribe(new, "sase-26")
        assert load_agent_tribes() == {existing: "alpha", new: "sase-26"}


def test_update_agent_tribe_validates_input(tmp_path: Path) -> None:
    store_path = tmp_path / "agent_tribes.json"
    identity = (AgentType.WORKFLOW, "sample", "ts")
    with _canonical_path(store_path):
        with pytest.raises(InvalidTribeError):
            update_agent_tribe(identity, "bad tribe")
        assert load_agent_tribes() == {}
