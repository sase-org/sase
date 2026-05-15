"""Tests for sase.workspace_provider.registry (Phase 3 of sase-3p)."""

from __future__ import annotations

import json
import os
import threading
from pathlib import Path
from unittest.mock import patch

import pytest

from sase.workspace_provider.registry import (
    REGISTRY_FILENAME,
    SCHEMA_VERSION,
    WorkspaceEntry,
    WorkspaceRegistry,
    load_or_init_registry,
    record_workspace,
    registry_path,
    remove_workspace,
    save_registry,
)
from sase.workspace_provider.store import (
    PRIMARY_WORKSPACE_NUM,
    WorkspaceStore,
)


def _make_store(tmp_path: Path, primary: str = "proj") -> WorkspaceStore:
    primary_dir = tmp_path / primary
    primary_dir.mkdir()
    return WorkspaceStore(
        str(primary_dir),
        config={
            "workspace": {
                "root": str(tmp_path / "root"),
                "project_key": "k",
            }
        },
        env={},
    )


class TestInit:
    def test_initializes_with_primary_zero(self, tmp_path: Path) -> None:
        store = _make_store(tmp_path)
        registry = load_or_init_registry(store)
        assert str(PRIMARY_WORKSPACE_NUM) in registry.workspaces
        entry = registry.workspaces[str(PRIMARY_WORKSPACE_NUM)]
        assert entry.role == "primary"
        assert entry.materialization == "primary"
        assert entry.checkout_dir == store.primary_workspace_dir
        assert entry.pinned is True

    def test_round_trips_via_disk(self, tmp_path: Path) -> None:
        store = _make_store(tmp_path)
        registry = load_or_init_registry(store)
        save_registry(store, registry)

        reloaded = load_or_init_registry(store)
        assert reloaded.project_key == registry.project_key
        assert reloaded.primary_workspace_dir == registry.primary_workspace_dir
        assert reloaded.schema_version == SCHEMA_VERSION

    def test_registry_path_under_root_dir(self, tmp_path: Path) -> None:
        store = _make_store(tmp_path)
        path = registry_path(store.root_dir)
        assert path == str(Path(store.root_dir) / REGISTRY_FILENAME)


class TestRecordAndRemove:
    def test_record_inserts_new_entry(self, tmp_path: Path) -> None:
        store = _make_store(tmp_path)
        wp = store.resolve(10)
        registry = record_workspace(store, wp, role="claim")
        assert "10" in registry.workspaces
        entry = registry.workspaces["10"]
        assert entry.checkout_dir == wp.checkout_dir
        assert entry.role == "claim"
        assert entry.created_at <= entry.last_used_at
        assert entry.materialization == wp.materialization

    def test_record_updates_existing_entry(self, tmp_path: Path) -> None:
        store = _make_store(tmp_path)
        wp = store.resolve(10)
        registry1 = record_workspace(store, wp)
        first_created = registry1.workspaces["10"].created_at
        first_used = registry1.workspaces["10"].last_used_at

        # Force time to advance so last_used_at strictly increases.
        with patch(
            "sase.workspace_provider.registry.time.time",
            return_value=first_used + 5,
        ):
            registry2 = record_workspace(store, wp)
        entry = registry2.workspaces["10"]
        assert entry.created_at == first_created
        assert entry.last_used_at == first_used + 5

    def test_record_persists_to_disk(self, tmp_path: Path) -> None:
        store = _make_store(tmp_path)
        wp = store.resolve(10)
        record_workspace(store, wp)

        with open(registry_path(store.root_dir), encoding="utf-8") as f:
            raw = json.load(f)
        assert "10" in raw["workspaces"]
        assert raw["schema_version"] == SCHEMA_VERSION
        assert raw["project_key"] == store.project_key

    def test_remove_drops_entry(self, tmp_path: Path) -> None:
        store = _make_store(tmp_path)
        record_workspace(store, store.resolve(10))
        registry = remove_workspace(store, 10)
        assert "10" not in registry.workspaces

    def test_remove_primary_is_noop(self, tmp_path: Path) -> None:
        store = _make_store(tmp_path)
        load_or_init_registry(store)
        save_registry(store, load_or_init_registry(store))
        registry = remove_workspace(store, PRIMARY_WORKSPACE_NUM)
        assert str(PRIMARY_WORKSPACE_NUM) in registry.workspaces


class TestAtomicity:
    def test_write_is_atomic_under_replace(self, tmp_path: Path) -> None:
        store = _make_store(tmp_path)
        registry = load_or_init_registry(store)
        save_registry(store, registry)
        path = registry_path(store.root_dir)

        original = Path(path).read_text(encoding="utf-8")

        # Simulate failure mid-write by raising inside os.replace; the
        # tempfile cleanup must leave the original file untouched.
        with patch(
            "sase.workspace_provider.registry.os.replace",
            side_effect=OSError("simulated"),
        ):
            with pytest.raises(OSError):
                save_registry(store, registry)

        assert Path(path).read_text(encoding="utf-8") == original

        leftovers = [
            p for p in os.listdir(store.root_dir) if p.startswith(".registry.")
        ]
        assert leftovers == []

    def test_concurrent_writes_do_not_corrupt(self, tmp_path: Path) -> None:
        store = _make_store(tmp_path)
        load_or_init_registry(store)

        def writer(num: int) -> None:
            record_workspace(store, store.resolve(num))

        threads = [threading.Thread(target=writer, args=(i,)) for i in range(10, 20)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # The file must still parse cleanly regardless of which writer won.
        with open(registry_path(store.root_dir), encoding="utf-8") as f:
            raw = json.load(f)
        assert raw["schema_version"] == SCHEMA_VERSION
        assert str(PRIMARY_WORKSPACE_NUM) in raw["workspaces"]


class TestReconciliation:
    def test_corrupt_file_treated_as_missing(self, tmp_path: Path) -> None:
        store = _make_store(tmp_path)
        os.makedirs(store.root_dir, exist_ok=True)
        Path(registry_path(store.root_dir)).write_text("not json", encoding="utf-8")

        registry = load_or_init_registry(store)
        assert registry.project_key == store.project_key
        assert str(PRIMARY_WORKSPACE_NUM) in registry.workspaces

    def test_load_reconciles_project_key(self, tmp_path: Path) -> None:
        store = _make_store(tmp_path)
        registry = WorkspaceRegistry(
            project_key="stale-key",
            primary_workspace_dir="/old/path",
            workspaces={
                "10": WorkspaceEntry(
                    checkout_dir="/old/path_10/",
                    materialization="git-clone",
                    role="claim",
                    created_at=1.0,
                    last_used_at=1.0,
                )
            },
        )
        save_registry(store, registry)

        reloaded = load_or_init_registry(store)
        assert reloaded.project_key == store.project_key
        assert reloaded.primary_workspace_dir == store.primary_workspace_dir
        # Existing entries are preserved.
        assert "10" in reloaded.workspaces

    def test_deleted_checkout_keeps_registry_entry(self, tmp_path: Path) -> None:
        store = _make_store(tmp_path)
        wp = store.resolve(10)
        record_workspace(store, wp)

        # Simulate the checkout disappearing from disk; the registry
        # entry survives so `repair`/`cleanup` can detect it.
        registry = load_or_init_registry(store)
        assert "10" in registry.workspaces
        entry = registry.workspaces["10"]
        assert not os.path.exists(entry.checkout_dir)
