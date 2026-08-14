"""Tests for sase.workspace_provider.lookup (Phase `lookup` of sase-lb.1)."""

from __future__ import annotations

from pathlib import Path

import pytest

from sase.workspace_provider.lookup import (
    resolve_consistent_workspace_pair,
    resolve_workspace_num_for_dir,
)
from sase.workspace_provider.registry import record_workspace
from sase.workspace_provider.store import WorkspaceStore


def _config(tmp_path: Path) -> dict:
    return {
        "workspace": {
            "root": str(tmp_path / "root"),
            "project_key": "k",
        }
    }


def _make_store(tmp_path: Path, primary: str = "proj") -> WorkspaceStore:
    primary_dir = tmp_path / primary
    primary_dir.mkdir()
    return WorkspaceStore(str(primary_dir), config=_config(tmp_path), env={})


def _resolve(store: WorkspaceStore, directory: str, *, tmp_path: Path) -> int | None:
    return resolve_workspace_num_for_dir(
        store.primary_workspace_dir,
        directory,
        config=_config(tmp_path),
        env={},
    )


class TestResolveWorkspaceNumForDir:
    def test_primary_checkout_resolves_to_zero(self, tmp_path: Path) -> None:
        store = _make_store(tmp_path)
        assert _resolve(store, store.primary_workspace_dir, tmp_path=tmp_path) == 0

    def test_managed_checkout_resolves_to_its_registry_number(
        self, tmp_path: Path
    ) -> None:
        store = _make_store(tmp_path)
        workspace_path = store.resolve(10)
        Path(workspace_path.checkout_dir).mkdir(parents=True)
        record_workspace(store, workspace_path)

        assert _resolve(store, workspace_path.checkout_dir, tmp_path=tmp_path) == 10

    def test_trailing_slash_spelling_resolves_identically(self, tmp_path: Path) -> None:
        store = _make_store(tmp_path)
        workspace_path = store.resolve(11)
        Path(workspace_path.checkout_dir).mkdir(parents=True)
        record_workspace(store, workspace_path)

        without_slash = workspace_path.checkout_dir.rstrip("/")
        assert _resolve(store, without_slash, tmp_path=tmp_path) == 11

    def test_symlinked_spelling_resolves_identically(self, tmp_path: Path) -> None:
        store = _make_store(tmp_path)
        workspace_path = store.resolve(12)
        real_dir = Path(workspace_path.checkout_dir.rstrip("/"))
        real_dir.mkdir(parents=True)
        record_workspace(store, workspace_path)

        symlink = tmp_path / "alias_to_12"
        symlink.symlink_to(real_dir)

        assert _resolve(store, str(symlink), tmp_path=tmp_path) == 12

    def test_tilde_relative_spelling_resolves_identically(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("HOME", str(tmp_path))
        store = _make_store(tmp_path)
        workspace_path = store.resolve(13)
        Path(workspace_path.checkout_dir).mkdir(parents=True)
        record_workspace(store, workspace_path)

        relative = workspace_path.checkout_dir.rstrip("/")[len(str(tmp_path)) :]
        assert _resolve(store, f"~{relative}", tmp_path=tmp_path) == 13

    def test_directory_outside_project_returns_none(self, tmp_path: Path) -> None:
        store = _make_store(tmp_path)
        outside = tmp_path / "unrelated"
        outside.mkdir()

        assert _resolve(store, str(outside), tmp_path=tmp_path) is None

    def test_existing_directory_missing_from_registry_returns_none(
        self, tmp_path: Path
    ) -> None:
        store = _make_store(tmp_path)
        workspace_path = store.resolve(14)
        Path(workspace_path.checkout_dir).mkdir(parents=True)
        # Deliberately not recorded in the registry.

        assert _resolve(store, workspace_path.checkout_dir, tmp_path=tmp_path) is None

    def test_empty_directory_returns_none(self, tmp_path: Path) -> None:
        store = _make_store(tmp_path)
        assert _resolve(store, "", tmp_path=tmp_path) is None


class TestResolveConsistentWorkspacePair:
    def test_truthy_number_is_returned_unchanged(self, tmp_path: Path) -> None:
        store = _make_store(tmp_path)

        assert resolve_consistent_workspace_pair(
            store.primary_workspace_dir,
            "/some/unregistered/dir",
            7,
            config=_config(tmp_path),
            env={},
        ) == ("/some/unregistered/dir", 7)

    def test_falsy_number_with_primary_dir_is_consistent(self, tmp_path: Path) -> None:
        store = _make_store(tmp_path)

        assert resolve_consistent_workspace_pair(
            store.primary_workspace_dir,
            store.primary_workspace_dir,
            0,
            config=_config(tmp_path),
            env={},
        ) == (store.primary_workspace_dir, 0)
        assert resolve_consistent_workspace_pair(
            store.primary_workspace_dir,
            store.primary_workspace_dir,
            None,
            config=_config(tmp_path),
            env={},
        ) == (store.primary_workspace_dir, 0)

    def test_falsy_number_with_registered_dir_is_repaired(self, tmp_path: Path) -> None:
        store = _make_store(tmp_path)
        workspace_path = store.resolve(15)
        Path(workspace_path.checkout_dir).mkdir(parents=True)
        record_workspace(store, workspace_path)

        assert resolve_consistent_workspace_pair(
            store.primary_workspace_dir,
            workspace_path.checkout_dir,
            0,
            config=_config(tmp_path),
            env={},
        ) == (workspace_path.checkout_dir, 15)

    def test_falsy_number_with_unregistered_dir_is_unresolvable(
        self, tmp_path: Path
    ) -> None:
        store = _make_store(tmp_path)
        workspace_path = store.resolve(16)
        Path(workspace_path.checkout_dir).mkdir(parents=True)
        # Deliberately not recorded in the registry.

        assert (
            resolve_consistent_workspace_pair(
                store.primary_workspace_dir,
                workspace_path.checkout_dir,
                None,
                config=_config(tmp_path),
                env={},
            )
            is None
        )

    def test_falsy_number_with_empty_dir_is_unresolvable(self, tmp_path: Path) -> None:
        store = _make_store(tmp_path)

        assert (
            resolve_consistent_workspace_pair(
                store.primary_workspace_dir,
                "",
                0,
                config=_config(tmp_path),
                env={},
            )
            is None
        )
