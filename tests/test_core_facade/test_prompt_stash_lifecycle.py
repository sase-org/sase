"""Tests for the Rust prompt-stash trash lifecycle facade and wires.

The v1 stash bindings keep their shape; the lifecycle read and mutation
endpoints use separately versioned results carrying both collections plus
changed/evicted ids. There is no Python lifecycle fallback: a stale wheel
fails clearly at the binding lookup.
"""

from __future__ import annotations

import types
from pathlib import Path
from typing import Any

import pytest

from sase.core import prompt_stash_facade as facade
from sase.core.prompt_stash_wire import (
    PROMPT_STASH_LIFECYCLE_WIRE_SCHEMA_VERSION,
    PROMPT_STASH_WIRE_SCHEMA_VERSION,
    PromptStashEntryWire,
    PromptStashLifecycleOutcomeWire,
    PromptStashLifecycleSnapshotWire,
    PromptStashTrashRecordWire,
    _prompt_stash_trash_record_from_dict,
    prompt_stash_lifecycle_outcome_from_dict,
    prompt_stash_lifecycle_snapshot_from_dict,
    prompt_stash_snapshot_from_dict,
)
from tests._rust_extension_module_helpers import (
    patch_rust_extension,
)

from sase.core.rust import RUST_EXTENSION_MODULE_NAME


TRASHED_AT = "2026-09-26T14:00:00+00:00"


def _entry_dict(entry_id: str, **overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "id": entry_id,
        "created_at": "2026-09-26T13:00:00+00:00",
        "text": f"draft {entry_id}",
    }
    payload.update(overrides)
    return payload


def _snapshot_dict(
    active: list[dict[str, Any]] | None = None,
    trash: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    return {
        "schema_version": PROMPT_STASH_LIFECYCLE_WIRE_SCHEMA_VERSION,
        "active": active if active is not None else [],
        "trash": trash if trash is not None else [],
        "stats": {"loaded_rows": (len(active or []) + len(trash or []))},
    }


def _outcome_dict(
    changed: list[str] | None = None,
    evicted: list[str] | None = None,
    **snapshot_kwargs: Any,
) -> dict[str, Any]:
    return {
        "schema_version": PROMPT_STASH_LIFECYCLE_WIRE_SCHEMA_VERSION,
        "changed": changed if changed is not None else [],
        "evicted": evicted if evicted is not None else [],
        "snapshot": _snapshot_dict(**snapshot_kwargs),
    }


def _trash_dict(entry_id: str) -> dict[str, Any]:
    return {"trashed_at": TRASHED_AT, "entry": _entry_dict(entry_id)}


def _fake_module(monkeypatch: pytest.MonkeyPatch, **bindings: Any) -> None:
    fake = types.ModuleType(RUST_EXTENSION_MODULE_NAME)
    for name, binding in bindings.items():
        setattr(fake, name, binding)
    patch_rust_extension(monkeypatch, fake)


def _skip_without_lifecycle_bindings(
    binding_name: str = "read_prompt_stash_lifecycle",
) -> None:
    rust_module = pytest.importorskip(RUST_EXTENSION_MODULE_NAME)
    if not hasattr(rust_module, binding_name):
        pytest.skip(f"sase_core_rs is too old (no {binding_name} binding).")


def test_lifecycle_snapshot_rehydrates_both_collections(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []

    def fake_read(path: str) -> dict[str, Any]:
        calls.append(path)
        return _snapshot_dict(
            active=[_entry_dict("a", pinned=True)],
            trash=[_trash_dict("t")],
        )

    _fake_module(monkeypatch, read_prompt_stash_lifecycle=fake_read)

    snapshot = facade.read_prompt_stash_lifecycle("/tmp/prompt_stash.jsonl")

    assert calls == ["/tmp/prompt_stash.jsonl"]
    assert isinstance(snapshot, PromptStashLifecycleSnapshotWire)
    assert [e.id for e in snapshot.active] == ["a"]
    assert snapshot.active[0].pinned is True
    assert len(snapshot.trash) == 1
    record = snapshot.trash[0]
    assert isinstance(record, PromptStashTrashRecordWire)
    assert record.trashed_at == TRASHED_AT
    assert record.entry.id == "t"
    assert record.entry.text == "draft t"
    assert snapshot.stats.loaded_rows == 2


def test_lifecycle_snapshot_schema_mismatch_fails_clearly(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_read(_path: str) -> dict[str, Any]:
        return {**_snapshot_dict(), "schema_version": 999}

    _fake_module(monkeypatch, read_prompt_stash_lifecycle=fake_read)

    with pytest.raises(ValueError, match="lifecycle wire schema mismatch"):
        facade.read_prompt_stash_lifecycle("/tmp/prompt_stash.jsonl")


def test_trash_passes_ids_limit_and_timestamp(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, list[str], int, str]] = []

    def fake_trash(
        path: str, ids: list[str], trash_limit: int, trashed_at: str
    ) -> dict[str, Any]:
        calls.append((path, ids, trash_limit, trashed_at))
        return _outcome_dict(changed=["a"], trash=[_trash_dict("a")])

    _fake_module(monkeypatch, trash_prompt_stash=fake_trash)

    outcome = facade.trash_prompt_stash(
        "/tmp/prompt_stash.jsonl", ("a", "b"), 20, TRASHED_AT
    )

    assert calls == [("/tmp/prompt_stash.jsonl", ["a", "b"], 20, TRASHED_AT)]
    assert isinstance(outcome, PromptStashLifecycleOutcomeWire)
    assert outcome.changed == ["a"]
    assert outcome.evicted == []
    assert [r.entry.id for r in outcome.snapshot.trash] == ["a"]


def test_trash_rejects_invalid_limits_before_touching_rust(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def unexpected(*args: Any) -> Any:
        raise AssertionError(f"rust binding must not run: {args!r}")

    _fake_module(monkeypatch, trash_prompt_stash=unexpected)

    for bad in (-1, True, False, "20", 2.0, None):
        with pytest.raises(ValueError, match="trash_limit"):
            facade.trash_prompt_stash("/tmp/prompt_stash.jsonl", ["a"], bad, TRASHED_AT)  # type: ignore[arg-type]
        with pytest.raises(ValueError, match="trash_limit"):
            facade.reconcile_prompt_stash_trash("/tmp/prompt_stash.jsonl", bad)  # type: ignore[arg-type]


def test_restore_passes_string_ids_and_rehydrates_outcome(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, list[str]]] = []

    def fake_restore(path: str, ids: list[str]) -> dict[str, Any]:
        calls.append((path, ids))
        return _outcome_dict(changed=["a"], active=[_entry_dict("b"), _entry_dict("a")])

    _fake_module(monkeypatch, restore_prompt_stash=fake_restore)

    outcome = facade.restore_prompt_stash("/tmp/prompt_stash.jsonl", ("a",))

    assert calls == [("/tmp/prompt_stash.jsonl", ["a"])]
    assert outcome.changed == ["a"]
    assert [e.id for e in outcome.snapshot.active] == ["b", "a"]


def test_purge_passes_string_ids_and_rehydrates_outcome(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, list[str]]] = []

    def fake_purge(path: str, ids: list[str]) -> dict[str, Any]:
        calls.append((path, ids))
        return _outcome_dict(changed=["a"])

    _fake_module(monkeypatch, purge_prompt_stash=fake_purge)

    outcome = facade.purge_prompt_stash("/tmp/prompt_stash.jsonl", ["a"])

    assert calls == [("/tmp/prompt_stash.jsonl", ["a"])]
    assert outcome.changed == ["a"]
    assert outcome.snapshot.trash == []


def test_reconcile_passes_limit_and_reports_evictions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, int]] = []

    def fake_reconcile(path: str, trash_limit: int) -> dict[str, Any]:
        calls.append((path, trash_limit))
        return _outcome_dict(evicted=["old"], trash=[_trash_dict("new")])

    _fake_module(monkeypatch, reconcile_prompt_stash_trash=fake_reconcile)

    outcome = facade.reconcile_prompt_stash_trash("/tmp/prompt_stash.jsonl", 1)

    assert calls == [("/tmp/prompt_stash.jsonl", 1)]
    assert outcome.changed == []
    assert outcome.evicted == ["old"]
    assert [r.entry.id for r in outcome.snapshot.trash] == ["new"]


def test_missing_lifecycle_binding_fails_clearly(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _fake_module(monkeypatch)

    with pytest.raises(AttributeError, match="read_prompt_stash_lifecycle"):
        facade.read_prompt_stash_lifecycle("/tmp/prompt_stash.jsonl")
    with pytest.raises(AttributeError, match="trash_prompt_stash"):
        facade.trash_prompt_stash("/tmp/prompt_stash.jsonl", ["a"], 20, TRASHED_AT)
    with pytest.raises(AttributeError, match="restore_prompt_stash"):
        facade.restore_prompt_stash("/tmp/prompt_stash.jsonl", ["a"])
    with pytest.raises(AttributeError, match="purge_prompt_stash"):
        facade.purge_prompt_stash("/tmp/prompt_stash.jsonl", ["a"])
    with pytest.raises(AttributeError, match="reconcile_prompt_stash_trash"):
        facade.reconcile_prompt_stash_trash("/tmp/prompt_stash.jsonl", 20)


def test_stale_wheel_error_names_reinstall(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _fake_module(monkeypatch)

    with pytest.raises(AttributeError, match="stale"):
        facade.read_prompt_stash_lifecycle("/tmp/prompt_stash.jsonl")


def test_lifecycle_lock_timeout_is_rehydrated_as_facade_exception(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class PromptStashLockTimeoutError(RuntimeError):
        pass

    def fake_trash(*args: Any) -> Any:
        raise PromptStashLockTimeoutError("prompt stash lock timed out after 2000ms")

    _fake_module(monkeypatch, trash_prompt_stash=fake_trash)

    with pytest.raises(
        facade.PromptStashLockTimeoutError,
        match="lock timed out",
    ):
        facade.trash_prompt_stash("/tmp/prompt_stash.jsonl", ["a"], 20, TRASHED_AT)


def test_trash_record_from_dict_requires_mapping_and_fields() -> None:
    record = _prompt_stash_trash_record_from_dict(_trash_dict("a"))
    assert record.trashed_at == TRASHED_AT
    assert record.entry.id == "a"
    with pytest.raises(ValueError, match="must be a dict"):
        _prompt_stash_trash_record_from_dict(["not", "a", "dict"])  # type: ignore[arg-type]
    with pytest.raises(KeyError):
        _prompt_stash_trash_record_from_dict({"entry": _entry_dict("a")})
    with pytest.raises(ValueError, match="lifecycle wire schema mismatch"):
        prompt_stash_lifecycle_snapshot_from_dict(
            {"schema_version": 999, "active": [], "trash": [], "stats": {}}
        )
    with pytest.raises(ValueError, match="lifecycle wire schema mismatch"):
        prompt_stash_lifecycle_outcome_from_dict(
            {
                "schema_version": 999,
                "changed": [],
                "evicted": [],
                "snapshot": _snapshot_dict(),
            }
        )


def test_lifecycle_outcome_preserves_full_entry() -> None:
    outcome = prompt_stash_lifecycle_outcome_from_dict(
        _outcome_dict(
            changed=["a"],
            active=[],
            trash=[
                {
                    "trashed_at": TRASHED_AT,
                    "entry": _entry_dict(
                        "a",
                        frontmatter="model: claude\n",
                        project="proj-a",
                        source="all",
                        pane_index=2,
                        pinned=True,
                        cursor={"pane_index": 1, "row": 2, "column": 3},
                    ),
                }
            ],
        )
    )
    record = outcome.snapshot.trash[0]
    assert record.entry.frontmatter == "model: claude\n"
    assert record.entry.project == "proj-a"
    assert record.entry.source == "all"
    assert record.entry.pane_index == 2
    assert record.entry.pinned is True
    assert record.entry.cursor is not None
    assert record.entry.cursor.row == 2


def test_v1_wire_shape_is_unchanged_by_lifecycle_addition() -> None:
    snapshot = prompt_stash_snapshot_from_dict(
        {
            "schema_version": PROMPT_STASH_WIRE_SCHEMA_VERSION,
            "entries": [_entry_dict("a")],
            "stats": {"loaded_rows": 1},
        }
    )
    assert PROMPT_STASH_WIRE_SCHEMA_VERSION == 1
    assert [e.id for e in snapshot.entries] == ["a"]
    assert not hasattr(snapshot, "active")
    assert not hasattr(snapshot, "trash")


def test_real_extension_trash_restore_purge_cycle(tmp_path: Path) -> None:
    _skip_without_lifecycle_bindings()
    path = tmp_path / "prompt_stash.jsonl"

    facade.append_prompt_stash(
        path,
        PromptStashEntryWire(
            id="a",
            created_at="2026-09-26T13:00:00+00:00",
            text="draft a",
            frontmatter="model: claude\n",
            project="proj-a",
            pinned=True,
        ),
    )
    facade.append_prompt_stash(
        path,
        PromptStashEntryWire(
            id="b",
            created_at="2026-09-26T13:01:00+00:00",
            text="draft b",
        ),
    )

    lifecycle = facade.read_prompt_stash_lifecycle(path)
    assert [e.id for e in lifecycle.active] == ["a", "b"]
    assert lifecycle.trash == []

    trashed = facade.trash_prompt_stash(path, ["a"], 20, TRASHED_AT)
    assert trashed.changed == ["a"]
    assert trashed.evicted == []
    assert [e.id for e in trashed.snapshot.active] == ["b"]
    assert len(trashed.snapshot.trash) == 1
    assert trashed.snapshot.trash[0].trashed_at == TRASHED_AT
    assert trashed.snapshot.trash[0].entry.frontmatter == "model: claude\n"
    assert trashed.snapshot.trash[0].entry.project == "proj-a"
    assert trashed.snapshot.trash[0].entry.pinned is True

    # The v1 readers keep working and see only the active rows.
    assert [e.id for e in facade.read_prompt_stash_snapshot(path).entries] == ["b"]

    restored = facade.restore_prompt_stash(path, ["a"])
    assert restored.changed == ["a"]
    assert [e.id for e in restored.snapshot.active] == ["b", "a"]
    assert restored.snapshot.trash == []

    facade.trash_prompt_stash(path, ["a"], 20, TRASHED_AT)
    purged = facade.purge_prompt_stash(path, ["a"])
    assert purged.changed == ["a"]
    assert purged.snapshot.trash == []
    assert [e.id for e in purged.snapshot.active] == ["b"]


def test_real_extension_enforces_limits_and_reconciles(tmp_path: Path) -> None:
    _skip_without_lifecycle_bindings("reconcile_prompt_stash_trash")
    path = tmp_path / "prompt_stash.jsonl"

    for entry_id in ("a", "b", "c"):
        facade.append_prompt_stash(
            path,
            PromptStashEntryWire(
                id=entry_id,
                created_at="2026-09-26T13:00:00+00:00",
                text=f"draft {entry_id}",
            ),
        )

    trashed = facade.trash_prompt_stash(path, ["a", "b", "c"], 1, TRASHED_AT)
    assert trashed.evicted == ["a", "b"]
    assert trashed.changed == ["c"]
    assert [r.entry.id for r in trashed.snapshot.trash] == ["c"]

    reconciled = facade.reconcile_prompt_stash_trash(path, 0)
    assert reconciled.changed == []
    assert reconciled.evicted == ["c"]
    assert reconciled.snapshot.trash == []


def test_real_extension_zero_limit_discards_without_recovery(
    tmp_path: Path,
) -> None:
    _skip_without_lifecycle_bindings("trash_prompt_stash")
    path = tmp_path / "prompt_stash.jsonl"

    facade.append_prompt_stash(
        path,
        PromptStashEntryWire(
            id="a",
            created_at="2026-09-26T13:00:00+00:00",
            text="draft a",
        ),
    )

    outcome = facade.trash_prompt_stash(path, ["a"], 0, TRASHED_AT)
    assert outcome.changed == []
    assert outcome.evicted == ["a"]
    assert outcome.snapshot.active == []
    assert outcome.snapshot.trash == []


def test_real_extension_lifecycle_schema_version_is_one() -> None:
    rust_module = pytest.importorskip(RUST_EXTENSION_MODULE_NAME)
    if not hasattr(rust_module, "prompt_stash_lifecycle_wire_schema_version"):
        pytest.skip("sase_core_rs is too old (no lifecycle schema binding).")
    assert rust_module.prompt_stash_lifecycle_wire_schema_version() == (
        PROMPT_STASH_LIFECYCLE_WIRE_SCHEMA_VERSION
    )
