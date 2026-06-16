"""Tests for the Rust prompt-stash store facade."""

from __future__ import annotations

import sys
import types
from pathlib import Path
from typing import Any

import pytest

from sase.core import prompt_stash_facade as facade
from sase.core.prompt_stash_wire import (
    PROMPT_STASH_WIRE_SCHEMA_VERSION,
    PromptStashEntryWire,
    _prompt_stash_entry_from_dict,
    prompt_stash_wire_to_json_dict,
)
from sase.core.rust import RUST_EXTENSION_MODULE_NAME


def _entry(
    id: str,
    *,
    text: str = "draft",
    frontmatter: str = "",
    project: str | None = None,
    source: str = "current",
    pane_index: int = 0,
) -> PromptStashEntryWire:
    return PromptStashEntryWire(
        id=id,
        created_at="2026-06-16T01:02:03+00:00",
        text=text,
        frontmatter=frontmatter,
        project=project,
        source=source,
        pane_index=pane_index,
    )


def _fake_module(monkeypatch: pytest.MonkeyPatch, **bindings: Any) -> None:
    fake = types.ModuleType(RUST_EXTENSION_MODULE_NAME)
    for name, binding in bindings.items():
        setattr(fake, name, binding)
    monkeypatch.setitem(sys.modules, RUST_EXTENSION_MODULE_NAME, fake)


def _skip_without_prompt_stash_bindings(
    binding_name: str = "read_prompt_stash_snapshot",
) -> None:
    rust_module = pytest.importorskip(RUST_EXTENSION_MODULE_NAME)
    if not hasattr(rust_module, binding_name):
        pytest.skip(f"sase_core_rs is too old (no {binding_name} binding).")


def test_read_snapshot_rehydrates_typed_records(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []

    def fake_read(path: str) -> dict:
        calls.append(path)
        return {
            "schema_version": PROMPT_STASH_WIRE_SCHEMA_VERSION,
            "entries": [
                {
                    "id": "e1",
                    "created_at": "2026-06-16T01:02:03+00:00",
                    "text": "hello",
                    "frontmatter": "model: claude\n",
                    "project": "proj-a",
                    "source": "all",
                    "pane_index": 2,
                }
            ],
            "stats": {
                "total_lines": 1,
                "blank_lines": 0,
                "invalid_json_lines": 0,
                "invalid_record_lines": 0,
                "loaded_rows": 1,
            },
        }

    _fake_module(monkeypatch, read_prompt_stash_snapshot=fake_read)

    snapshot = facade.read_prompt_stash_snapshot("/tmp/prompt_stash.jsonl")

    assert calls == ["/tmp/prompt_stash.jsonl"]
    assert snapshot.stats.loaded_rows == 1
    entry = snapshot.entries[0]
    assert isinstance(entry, PromptStashEntryWire)
    assert entry.id == "e1"
    assert entry.project == "proj-a"
    assert entry.source == "all"
    assert entry.pane_index == 2


def test_missing_prompt_stash_binding_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _fake_module(monkeypatch)

    with pytest.raises(AttributeError, match="read_prompt_stash_snapshot"):
        facade.read_prompt_stash_snapshot("/tmp/prompt_stash.jsonl")


def test_schema_mismatch_fails_clearly(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_read(_path: str) -> dict:
        return {"schema_version": 999, "entries": [], "stats": {}}

    _fake_module(monkeypatch, read_prompt_stash_snapshot=fake_read)

    with pytest.raises(ValueError, match="prompt stash wire schema mismatch"):
        facade.read_prompt_stash_snapshot("/tmp/prompt_stash.jsonl")


def test_append_serializes_entry_dict(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[str, dict[str, Any]]] = []

    def fake_append(path: str, entry: dict[str, Any]) -> dict:
        calls.append((path, entry))
        return {
            "schema_version": PROMPT_STASH_WIRE_SCHEMA_VERSION,
            "entries": [entry],
            "stats": {"loaded_rows": 1},
        }

    _fake_module(monkeypatch, append_prompt_stash=fake_append)

    snapshot = facade.append_prompt_stash(
        "/tmp/prompt_stash.jsonl", _entry("e1", project="proj-a")
    )

    assert len(calls) == 1
    assert calls[0][0] == "/tmp/prompt_stash.jsonl"
    assert calls[0][1]["id"] == "e1"
    assert calls[0][1]["project"] == "proj-a"
    assert snapshot.entries[0].id == "e1"


def test_pop_passes_string_ids_and_rehydrates_outcome(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, list[str]]] = []

    def fake_pop(path: str, ids: list[str]) -> dict:
        calls.append((path, ids))
        return {
            "schema_version": PROMPT_STASH_WIRE_SCHEMA_VERSION,
            "removed": [
                {
                    "id": "a",
                    "created_at": "2026-06-16T01:02:03+00:00",
                    "text": "x",
                }
            ],
            "snapshot": {
                "schema_version": PROMPT_STASH_WIRE_SCHEMA_VERSION,
                "entries": [],
                "stats": {},
            },
        }

    _fake_module(monkeypatch, pop_prompt_stash=fake_pop)

    outcome = facade.pop_prompt_stash("/tmp/prompt_stash.jsonl", ("a", "b"))

    assert calls == [("/tmp/prompt_stash.jsonl", ["a", "b"])]
    assert [e.id for e in outcome.removed] == ["a"]
    assert outcome.snapshot.entries == []


def test_wire_helpers_round_trip_entry() -> None:
    entry = _entry("e1", project="proj-a", frontmatter="m: c\n", pane_index=3)
    payload = prompt_stash_wire_to_json_dict(entry)
    assert payload == {
        "id": "e1",
        "created_at": "2026-06-16T01:02:03+00:00",
        "text": "draft",
        "frontmatter": "m: c\n",
        "project": "proj-a",
        "source": "current",
        "pane_index": 3,
    }
    assert _prompt_stash_entry_from_dict(payload) == entry


def test_entry_from_dict_applies_defaults() -> None:
    entry = _prompt_stash_entry_from_dict(
        {"id": "e1", "created_at": "2026-06-16T01:02:03+00:00"}
    )
    assert entry.text == ""
    assert entry.frontmatter == ""
    assert entry.project is None
    assert entry.source == ""
    assert entry.pane_index == 0


def test_real_extension_round_trips_store_operations(tmp_path: Path) -> None:
    _skip_without_prompt_stash_bindings()
    path = tmp_path / "prompt_stash.jsonl"

    append = facade.append_prompt_stash(
        path, _entry("a", project="proj-a", frontmatter="model: claude\n")
    )
    assert [e.id for e in append.entries] == ["a"]
    assert append.entries[0].project == "proj-a"
    assert append.entries[0].frontmatter == "model: claude\n"

    facade.append_prompt_stash(path, _entry("b", source="all", pane_index=1))
    snapshot = facade.read_prompt_stash_snapshot(path)
    assert [e.id for e in snapshot.entries] == ["a", "b"]
    assert snapshot.stats.loaded_rows == 2

    pop = facade.pop_prompt_stash(path, ["a"])
    assert [e.id for e in pop.removed] == ["a"]
    assert [e.id for e in pop.snapshot.entries] == ["b"]

    after = facade.read_prompt_stash_snapshot(path)
    assert [e.id for e in after.entries] == ["b"]


def test_real_extension_missing_file_is_empty(tmp_path: Path) -> None:
    _skip_without_prompt_stash_bindings()
    path = tmp_path / "prompt_stash.jsonl"

    snapshot = facade.read_prompt_stash_snapshot(path)

    assert snapshot.entries == []
    assert snapshot.stats.loaded_rows == 0


def test_real_extension_rewrite_merges_unseen_rows(tmp_path: Path) -> None:
    _skip_without_prompt_stash_bindings("rewrite_prompt_stash")
    path = tmp_path / "prompt_stash.jsonl"
    facade.rewrite_prompt_stash(path, [_entry("a"), _entry("b")])

    snapshot = facade.rewrite_prompt_stash(
        path, [_entry("a", text="updated"), _entry("c")]
    )

    ids = [e.id for e in snapshot.entries]
    assert ids == ["a", "c", "b"]
    a = next(e for e in snapshot.entries if e.id == "a")
    assert a.text == "updated"
