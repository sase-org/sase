"""Tests for sase.workspace_provider.lookup (Phase `lookup` of sase-lb.1)."""

from __future__ import annotations

from pathlib import Path

import pytest

from sase.workspace_provider.lookup import (
    resolve_consistent_workspace_pair,
    resolve_workspace_num_for_dir,
    resolve_workspace_owner_for_path,
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


def _resolve_owner(
    store: WorkspaceStore, directory: str, *, tmp_path: Path
) -> tuple[int, str] | None:
    return resolve_workspace_owner_for_path(
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


class TestResolveWorkspaceOwnerForPath:
    def test_path_nested_in_numbered_workspace_returns_its_owner(
        self, tmp_path: Path
    ) -> None:
        store = _make_store(tmp_path)
        workspace_path = store.resolve(20)
        checkout = Path(workspace_path.checkout_dir)
        checkout.mkdir(parents=True)
        record_workspace(store, workspace_path)
        nested = checkout / "sase" / "repos" / "external" / "gh" / "x"
        nested.mkdir(parents=True)

        assert _resolve_owner(store, str(nested), tmp_path=tmp_path) == (
            20,
            str(checkout),
        )

    def test_workspace_root_itself_returns_its_owner(self, tmp_path: Path) -> None:
        store = _make_store(tmp_path)
        workspace_path = store.resolve(21)
        checkout = Path(workspace_path.checkout_dir)
        checkout.mkdir(parents=True)
        record_workspace(store, workspace_path)

        assert _resolve_owner(
            store, workspace_path.checkout_dir, tmp_path=tmp_path
        ) == (21, str(checkout))

    def test_path_nested_under_primary_returns_primary(self, tmp_path: Path) -> None:
        store = _make_store(tmp_path)
        nested = Path(store.primary_workspace_dir) / "sase" / "repos" / "plans"
        nested.mkdir(parents=True)

        assert _resolve_owner(store, str(nested), tmp_path=tmp_path) == (
            0,
            store.primary_workspace_dir,
        )

    def test_deepest_containing_checkout_wins_when_checkouts_nest(
        self, tmp_path: Path
    ) -> None:
        store = _make_store(tmp_path)
        outer_path = store.resolve(22)
        outer = Path(outer_path.checkout_dir)
        outer.mkdir(parents=True)
        record_workspace(store, outer_path)

        inner = outer / "sase" / "repos" / "external" / "gh" / "nested-clone"
        inner.mkdir(parents=True)
        inner_entry = store.resolve(23)
        # Point the inner registry entry's checkout_dir at a path nested
        # inside the outer checkout to exercise longest-prefix precedence.
        from dataclasses import replace

        inner_path = replace(inner_entry, checkout_dir=str(inner))
        record_workspace(store, inner_path)

        deeper = inner / "leaf"
        deeper.mkdir(parents=True)

        assert _resolve_owner(store, str(deeper), tmp_path=tmp_path) == (
            23,
            str(inner),
        )

    def test_unmanaged_path_returns_none(self, tmp_path: Path) -> None:
        store = _make_store(tmp_path)
        outside = tmp_path / "unrelated"
        outside.mkdir()

        assert _resolve_owner(store, str(outside), tmp_path=tmp_path) is None

    def test_empty_directory_returns_none(self, tmp_path: Path) -> None:
        store = _make_store(tmp_path)
        assert _resolve_owner(store, "", tmp_path=tmp_path) is None


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

    def test_falsy_number_with_nested_dir_repairs_to_owning_pair(
        self, tmp_path: Path
    ) -> None:
        store = _make_store(tmp_path)
        workspace_path = store.resolve(17)
        checkout = Path(workspace_path.checkout_dir)
        checkout.mkdir(parents=True)
        record_workspace(store, workspace_path)
        nested = checkout / "sase" / "repos" / "external" / "gh" / "x"
        nested.mkdir(parents=True)

        assert resolve_consistent_workspace_pair(
            store.primary_workspace_dir,
            str(nested),
            0,
            config=_config(tmp_path),
            env={},
        ) == (str(checkout), 17)

    def test_falsy_number_with_dir_nested_under_primary_repairs_to_primary(
        self, tmp_path: Path
    ) -> None:
        store = _make_store(tmp_path)
        nested = Path(store.primary_workspace_dir) / "sase" / "repos" / "plans"
        nested.mkdir(parents=True)

        assert resolve_consistent_workspace_pair(
            store.primary_workspace_dir,
            str(nested),
            None,
            config=_config(tmp_path),
            env={},
        ) == (store.primary_workspace_dir, 0)

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

    def test_falsy_number_with_unmanaged_nested_dir_is_unresolvable(
        self, tmp_path: Path
    ) -> None:
        store = _make_store(tmp_path)
        unmanaged = tmp_path / "unrelated"
        nested = unmanaged / "sub"
        nested.mkdir(parents=True)

        assert (
            resolve_consistent_workspace_pair(
                store.primary_workspace_dir,
                str(nested),
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
