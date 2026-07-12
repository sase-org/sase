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
    pinned: bool = False,
) -> PromptStashEntryWire:
    return PromptStashEntryWire(
        id=id,
        created_at="2026-06-16T01:02:03+00:00",
        text=text,
        frontmatter=frontmatter,
        project=project,
        source=source,
        pane_index=pane_index,
        pinned=pinned,
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
                    "pinned": True,
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
    assert entry.pinned is True


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


def test_lock_timeout_is_rehydrated_as_distinct_facade_exception(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class PromptStashLockTimeoutError(RuntimeError):
        pass

    def fake_read(_path: str) -> dict[str, Any]:
        raise PromptStashLockTimeoutError("prompt stash lock timed out after 2000ms")

    _fake_module(monkeypatch, read_prompt_stash_snapshot=fake_read)

    with pytest.raises(
        facade.PromptStashLockTimeoutError,
        match="lock timed out",
    ):
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
    assert calls[0][1]["pinned"] is False
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


def test_set_pinned_passes_string_ids_and_rehydrates_snapshot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, list[str], bool]] = []

    def fake_set_pinned(path: str, ids: list[str], pinned: bool) -> dict:
        calls.append((path, ids, pinned))
        return {
            "schema_version": PROMPT_STASH_WIRE_SCHEMA_VERSION,
            "entries": [
                {
                    "id": "a",
                    "created_at": "2026-06-16T01:02:03+00:00",
                    "text": "x",
                    "pinned": pinned,
                }
            ],
            "stats": {"loaded_rows": 1},
        }

    _fake_module(monkeypatch, set_prompt_stash_pinned=fake_set_pinned)

    snapshot = facade.set_prompt_stash_pinned(
        "/tmp/prompt_stash.jsonl", ("a", "b"), True
    )

    assert calls == [("/tmp/prompt_stash.jsonl", ["a", "b"], True)]
    assert snapshot.entries[0].id == "a"
    assert snapshot.entries[0].pinned is True


def test_rewrite_serializes_entries_and_rehydrates_snapshot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, list[dict[str, Any]]]] = []

    def fake_rewrite(path: str, entries: list[dict[str, Any]]) -> dict:
        calls.append((path, entries))
        return {
            "schema_version": PROMPT_STASH_WIRE_SCHEMA_VERSION,
            "entries": entries,
            "stats": {"loaded_rows": len(entries)},
        }

    _fake_module(monkeypatch, rewrite_prompt_stash=fake_rewrite)

    snapshot = facade.rewrite_prompt_stash(
        "/tmp/prompt_stash.jsonl",
        [
            _entry(
                "pin",
                text="updated",
                frontmatter="model: c",
                project="proj-a",
                pinned=True,
            )
        ],
    )

    assert len(calls) == 1
    assert calls[0][0] == "/tmp/prompt_stash.jsonl"
    assert calls[0][1][0]["id"] == "pin"
    assert calls[0][1][0]["text"] == "updated"
    assert calls[0][1][0]["frontmatter"] == "model: c"
    assert calls[0][1][0]["pinned"] is True
    assert snapshot.entries[0].id == "pin"
    assert snapshot.entries[0].text == "updated"


def test_wire_helpers_round_trip_entry() -> None:
    entry = _entry(
        "e1",
        project="proj-a",
        frontmatter="m: c\n",
        pane_index=3,
        pinned=True,
    )
    payload = prompt_stash_wire_to_json_dict(entry)
    assert payload == {
        "id": "e1",
        "created_at": "2026-06-16T01:02:03+00:00",
        "text": "draft",
        "frontmatter": "m: c\n",
        "project": "proj-a",
        "source": "current",
        "pane_index": 3,
        "pinned": True,
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
    assert entry.pinned is False


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


def test_real_extension_sets_and_clears_pinned(tmp_path: Path) -> None:
    _skip_without_prompt_stash_bindings("set_prompt_stash_pinned")
    path = tmp_path / "prompt_stash.jsonl"

    facade.append_prompt_stash(path, _entry("a"))
    facade.append_prompt_stash(path, _entry("b"))

    pinned = facade.set_prompt_stash_pinned(path, ["a", "missing"], True)
    assert [(e.id, e.pinned) for e in pinned.entries] == [("a", True), ("b", False)]

    cleared = facade.set_prompt_stash_pinned(path, ["a"], False)
    assert [(e.id, e.pinned) for e in cleared.entries] == [
        ("a", False),
        ("b", False),
    ]


def test_real_extension_rewrite_updates_one_entry_in_place(tmp_path: Path) -> None:
    _skip_without_prompt_stash_bindings("rewrite_prompt_stash")
    path = tmp_path / "prompt_stash.jsonl"

    facade.append_prompt_stash(
        path,
        _entry(
            "pin",
            text="old",
            frontmatter="old: fm",
            project="proj-a",
            pinned=True,
        ),
    )
    facade.append_prompt_stash(path, _entry("other", text="keep"))
    original = {
        entry.id: entry for entry in facade.read_prompt_stash_snapshot(path).entries
    }

    updated = facade.rewrite_prompt_stash(
        path,
        [
            PromptStashEntryWire(
                id="pin",
                created_at=original["pin"].created_at,
                text="new text",
                frontmatter="model: c",
                project=original["pin"].project,
                source=original["pin"].source,
                pane_index=original["pin"].pane_index,
                pinned=original["pin"].pinned,
            )
        ],
    )

    entries = {entry.id: entry for entry in updated.entries}
    assert entries["pin"].text == "new text"
    assert entries["pin"].frontmatter == "model: c"
    assert entries["pin"].id == original["pin"].id
    assert entries["pin"].created_at == original["pin"].created_at
    assert entries["pin"].pinned is True
    assert entries["other"] == original["other"]


def test_real_extension_missing_file_is_empty(tmp_path: Path) -> None:
    _skip_without_prompt_stash_bindings()
    path = tmp_path / "prompt_stash.jsonl"

    snapshot = facade.read_prompt_stash_snapshot(path)

    assert snapshot.entries == []
    assert snapshot.stats.loaded_rows == 0


# --- Phase 4 hardening: malformed / old-schema store tolerance -------------


def test_real_extension_tolerates_malformed_lines(tmp_path: Path) -> None:
    """A hand-corrupted store loads its valid rows and skips the junk.

    Phase 4 pins the durability contract: blank lines, non-JSON lines, and
    well-formed JSON that is missing the required ``id`` / ``created_at`` keys
    are all dropped (and counted in ``stats``) rather than crashing the read,
    so a partially-written or older-tool store still surfaces what it can.
    """
    _skip_without_prompt_stash_bindings()
    path = tmp_path / "prompt_stash.jsonl"
    path.write_text(
        "\n"  # blank line
        '{"id": "good1", "created_at": "2026-06-16T01:02:03+00:00", '
        '"text": "first"}\n'
        "   \n"  # whitespace-only line
        "this is not json at all\n"  # invalid JSON
        '{"created_at": "2026-06-16T01:02:04+00:00", "text": "no id"}\n'  # no id
        '{"id": "noTimestamp", "text": "no created_at"}\n'  # no created_at
        '{"id": "good2", "created_at": "2026-06-16T01:02:05+00:00", '
        '"text": "second", "future_field": "ignored"}\n',  # forward-compat key
        encoding="utf-8",
    )

    snapshot = facade.read_prompt_stash_snapshot(path)

    # Only the two complete records survive; the forward-compatible unknown
    # key on ``good2`` is ignored rather than rejected (old/new schema mix).
    assert [e.id for e in snapshot.entries] == ["good1", "good2"]
    assert [e.text for e in snapshot.entries] == ["first", "second"]
    stats = snapshot.stats
    assert stats.loaded_rows == 2
    assert stats.blank_lines == 2
    assert stats.invalid_json_lines == 1
    assert stats.invalid_record_lines == 2


def test_real_extension_pop_skips_malformed_lines(tmp_path: Path) -> None:
    """Popping from a partly-corrupt store still removes a valid row."""
    _skip_without_prompt_stash_bindings("pop_prompt_stash")
    path = tmp_path / "prompt_stash.jsonl"
    path.write_text(
        "garbage line\n"
        '{"id": "keep", "created_at": "2026-06-16T01:02:03+00:00", '
        '"text": "keep"}\n'
        '{"id": "drop", "created_at": "2026-06-16T01:02:04+00:00", '
        '"text": "drop"}\n',
        encoding="utf-8",
    )

    outcome = facade.pop_prompt_stash(path, ["drop"])

    assert [e.id for e in outcome.removed] == ["drop"]
    assert [e.id for e in outcome.snapshot.entries] == ["keep"]


# --- Phase 4 hardening: graceful degradation when the binding is missing ---


def test_read_degrades_when_binding_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The app's count/read paths floor to empty when ``sase_core_rs`` is gone.

    The facade itself raises (the strict-loader contract), but the TUI read
    helpers wrap it; this pins that an unimportable wheel never crashes the
    app, mirroring how the handler degrades a failed capture into a toast.
    """
    from sase.ace.tui.actions.agent_workflow._prompt_bar_stash import (
        PromptBarStashMixin,
    )

    def _boom(_name: str) -> Any:
        raise ImportError("sase_core_rs is not importable in this environment")

    monkeypatch.setattr(facade, "require_rust_binding", _boom)
    monkeypatch.setattr(
        "sase.core.paths.prompt_stash_path",
        lambda: Path("/tmp/does-not-matter.jsonl"),
    )

    class _Probe(PromptBarStashMixin):
        pass

    probe = _Probe()
    assert probe._read_prompt_stash_count() == 0
    assert probe._read_prompt_stash_entries() == []
