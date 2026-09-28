"""Tests for the Rust prompt-stash archive facade and wires.

The archive endpoints use a separately versioned snapshot carrying
newest-first records plus whole-file stats. Recovery returns the lifecycle
outcome shape with recovered ids in ``changed``; the archive itself stays
append-only.
"""

from __future__ import annotations

import types
from pathlib import Path
from typing import Any

import pytest

from sase.core import prompt_stash_facade as facade
from sase.core.prompt_stash_wire import (
    PROMPT_STASH_ARCHIVE_WIRE_SCHEMA_VERSION,
    PromptStashArchiveSnapshotWire,
)
from sase.core.rust import RUST_EXTENSION_MODULE_NAME
from tests._rust_extension_module_helpers import patch_rust_extension


def _entry_dict(entry_id: str, **overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "id": entry_id,
        "created_at": "2026-09-26T13:00:00+00:00",
        "text": f"draft {entry_id}",
    }
    payload.update(overrides)
    return payload


def _record_dict(entry_id: str, reason: str = "popped") -> dict[str, Any]:
    return {
        "kind": "archived",
        "archived_at": "2026-09-26T14:00:00+00:00",
        "reason": reason,
        "pid": 1234,
        "entry": _entry_dict(entry_id),
    }


def _snapshot_dict(records: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    records = records if records is not None else []
    return {
        "schema_version": PROMPT_STASH_ARCHIVE_WIRE_SCHEMA_VERSION,
        "records": records,
        "stats": {"loaded_rows": len(records)},
    }


def _fake_module(monkeypatch: pytest.MonkeyPatch, **bindings: Any) -> None:
    fake = types.ModuleType(RUST_EXTENSION_MODULE_NAME)
    for name, binding in bindings.items():
        setattr(fake, name, binding)
    patch_rust_extension(monkeypatch, fake)


def _skip_without_archive_bindings() -> None:
    rust_module = pytest.importorskip(RUST_EXTENSION_MODULE_NAME)
    for name in ("read_prompt_stash_archive", "recover_prompt_stash_archive"):
        if not hasattr(rust_module, name):
            pytest.skip(f"sase_core_rs is too old (no {name} binding).")


def test_archive_snapshot_rehydrates_records(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[str, int]] = []

    def fake_read(path: str, limit: int) -> dict[str, Any]:
        calls.append((path, limit))
        return _snapshot_dict([_record_dict("a"), _record_dict("b", reason="purged")])

    _fake_module(monkeypatch, read_prompt_stash_archive=fake_read)

    snapshot = facade.read_prompt_stash_archive("/tmp/prompt_stash.jsonl", 20)

    assert calls == [("/tmp/prompt_stash.jsonl", 20)]
    assert isinstance(snapshot, PromptStashArchiveSnapshotWire)
    assert [record.entry.id for record in snapshot.records] == ["a", "b"]
    assert [record.reason for record in snapshot.records] == ["popped", "purged"]
    assert snapshot.records[0].kind == "archived"
    assert snapshot.records[0].pid == 1234
    assert snapshot.records[0].trashed_at is None
    assert snapshot.stats.loaded_rows == 2


def test_archive_snapshot_schema_mismatch_fails_clearly(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_read(_path: str, _limit: int) -> dict[str, Any]:
        return {**_snapshot_dict(), "schema_version": 999}

    _fake_module(monkeypatch, read_prompt_stash_archive=fake_read)

    with pytest.raises(ValueError, match="archive wire schema mismatch"):
        facade.read_prompt_stash_archive("/tmp/prompt_stash.jsonl")


def test_recover_passes_ids_and_returns_lifecycle_outcome(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, list[str]]] = []

    def fake_recover(path: str, ids: list[str]) -> dict[str, Any]:
        calls.append((path, ids))
        return {
            "schema_version": 1,
            "changed": ids,
            "evicted": [],
            "snapshot": {
                "schema_version": 1,
                "active": [_entry_dict(ids[0])],
                "trash": [],
                "stats": {"loaded_rows": 1},
            },
        }

    _fake_module(monkeypatch, recover_prompt_stash_archive=fake_recover)

    outcome = facade.recover_prompt_stash_archive("/tmp/prompt_stash.jsonl", ["a"])

    assert calls == [("/tmp/prompt_stash.jsonl", ["a"])]
    assert outcome.changed == ["a"]
    assert [entry.id for entry in outcome.snapshot.active] == ["a"]


def test_archive_round_trip_through_real_bindings(tmp_path: Path) -> None:
    _skip_without_archive_bindings()
    from sase.core.prompt_stash_wire import PromptStashEntryWire

    path = tmp_path / "prompt_stash.jsonl"
    facade.append_prompt_stash(
        path,
        PromptStashEntryWire(
            id="gone",
            created_at="2026-09-26T13:00:00+00:00",
            text="round trip draft",
            source="test",
        ),
    )
    facade.pop_prompt_stash(path, ["gone"])

    snapshot = facade.read_prompt_stash_archive(path, 20)
    assert [record.entry.id for record in snapshot.records] == ["gone"]
    assert snapshot.records[0].reason == "popped"

    outcome = facade.recover_prompt_stash_archive(path, ["gone"])
    assert outcome.changed == ["gone"]
    assert [e.id for e in facade.read_prompt_stash_snapshot(path).entries] == ["gone"]
    # Recovery is append-only: the archive line stays put.
    assert [r.entry.id for r in facade.read_prompt_stash_archive(path, 20).records] == [
        "gone"
    ]
