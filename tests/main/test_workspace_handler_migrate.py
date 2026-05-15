"""Tests for ``sase workspace migrate`` (and the symlink-aware cleanup path)."""

from __future__ import annotations

import os
import time
from pathlib import Path

import pytest

from sase.main.workspace_handler import handle_workspace_command
from sase.workspace_provider.registry import (
    load_or_init_registry,
    save_registry,
)
from sase.workspace_provider.marker import read_marker
from sase.workspace_provider.store import WorkspaceStore
from tests.main.workspace_handler_helpers import make_args, project_layout

__all__ = ["project_layout"]


class TestMigrate:
    def _make_adjacent(self, primary: Path, num: int) -> Path:
        adj = primary.parent / f"{primary.name}_{num}"
        adj.mkdir()
        (adj / ".git").mkdir()
        (adj / "marker.txt").write_text(f"workspace {num}\n", encoding="utf-8")
        return adj

    def test_migrate_moves_adjacent_to_managed(
        self,
        project_layout: tuple[str, str, Path],
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        project_name, _, primary = project_layout
        adj = self._make_adjacent(primary, 10)

        args = make_args(
            workspace_subcommand="migrate",
            project=project_name,
            to="xdg-state",
            symlink_transition=False,
            finalize=False,
            dry_run=False,
        )
        with pytest.raises(SystemExit) as exc:
            handle_workspace_command(args)
        assert exc.value.code == 0
        out = capsys.readouterr().out
        assert "migrating #10" in out
        # Source no longer exists; managed destination has the content.
        assert not adj.exists()
        # Build the target store the same way the handler does so we can
        # inspect the resulting managed checkout path.
        target_store = WorkspaceStore(
            str(primary),
            config={
                "workspace": {
                    "root": "xdg-state",
                    "project_key": "demo-key",
                }
            },
        )
        managed = Path(target_store.resolve(10).checkout_dir.rstrip("/"))
        assert managed.is_dir()
        assert (managed / "marker.txt").read_text(encoding="utf-8") == "workspace 10\n"
        # Registry under the new root knows about #10.
        registry = load_or_init_registry(target_store)
        assert "10" in registry.workspaces
        marker = read_marker(str(managed))
        assert marker is not None
        assert marker.project_name == project_name
        assert marker.workspace_num == 10
        assert marker.primary_workspace_dir == str(primary)

    def test_migrate_with_symlink_transition_creates_symlink(
        self,
        project_layout: tuple[str, str, Path],
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        project_name, _, primary = project_layout
        adj = self._make_adjacent(primary, 11)

        args = make_args(
            workspace_subcommand="migrate",
            project=project_name,
            to="xdg-state",
            symlink_transition=True,
            finalize=False,
            dry_run=False,
        )
        with pytest.raises(SystemExit):
            handle_workspace_command(args)
        capsys.readouterr()

        target_store = WorkspaceStore(
            str(primary),
            config={
                "workspace": {
                    "root": "xdg-state",
                    "project_key": "demo-key",
                }
            },
        )
        managed = Path(target_store.resolve(11).checkout_dir.rstrip("/"))
        assert managed.is_dir()
        # Adjacent path is now a symlink to the managed checkout.
        assert adj.is_symlink()
        assert os.readlink(adj) == str(managed)
        # Deleting the symlink leaves the canonical checkout untouched.
        adj.unlink()
        assert managed.is_dir()
        assert (managed / "marker.txt").exists()

    def test_migrate_dry_run_does_not_move(
        self,
        project_layout: tuple[str, str, Path],
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        project_name, _, primary = project_layout
        adj = self._make_adjacent(primary, 12)

        args = make_args(
            workspace_subcommand="migrate",
            project=project_name,
            to="xdg-state",
            symlink_transition=True,
            finalize=False,
            dry_run=True,
        )
        with pytest.raises(SystemExit) as exc:
            handle_workspace_command(args)
        assert exc.value.code == 0
        out = capsys.readouterr().out
        assert "would migrate #12" in out
        assert "would symlink" in out
        assert adj.exists()
        assert not adj.is_symlink()

    def test_migrate_refuses_to_overwrite_existing_managed(
        self,
        project_layout: tuple[str, str, Path],
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        project_name, _, primary = project_layout
        adj = self._make_adjacent(primary, 13)

        # Pre-create the managed destination so migration must refuse.
        target_store = WorkspaceStore(
            str(primary),
            config={
                "workspace": {
                    "root": "xdg-state",
                    "project_key": "demo-key",
                }
            },
        )
        managed = Path(target_store.resolve(13).checkout_dir.rstrip("/"))
        managed.mkdir(parents=True)
        (managed / "pre-existing").write_text("keep me\n", encoding="utf-8")

        args = make_args(
            workspace_subcommand="migrate",
            project=project_name,
            to="xdg-state",
            symlink_transition=False,
            finalize=False,
            dry_run=False,
        )
        with pytest.raises(SystemExit) as exc:
            handle_workspace_command(args)
        assert exc.value.code == 1
        captured = capsys.readouterr()
        assert "refusing to overwrite" in captured.err
        # Adjacent dir is untouched.
        assert adj.exists()
        assert (managed / "pre-existing").read_text(encoding="utf-8") == "keep me\n"

    def test_finalize_removes_transition_symlinks(
        self,
        project_layout: tuple[str, str, Path],
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        project_name, _, primary = project_layout
        adj = self._make_adjacent(primary, 14)
        # First migrate with symlink transition.
        migrate_args = make_args(
            workspace_subcommand="migrate",
            project=project_name,
            to="xdg-state",
            symlink_transition=True,
            finalize=False,
            dry_run=False,
        )
        with pytest.raises(SystemExit):
            handle_workspace_command(migrate_args)
        capsys.readouterr()
        assert adj.is_symlink()

        target_store = WorkspaceStore(
            str(primary),
            config={
                "workspace": {
                    "root": "xdg-state",
                    "project_key": "demo-key",
                }
            },
        )
        managed = Path(target_store.resolve(14).checkout_dir.rstrip("/"))

        # Finalize removes the symlink but leaves the managed checkout.
        finalize_args = make_args(
            workspace_subcommand="migrate",
            project=project_name,
            to=None,
            symlink_transition=False,
            finalize=True,
            dry_run=False,
        )
        with pytest.raises(SystemExit) as exc:
            handle_workspace_command(finalize_args)
        assert exc.value.code == 0
        out = capsys.readouterr().out
        assert "removing transition symlink #14" in out
        assert not adj.exists()
        assert managed.is_dir()

    def test_cleanup_removes_symlink_and_target(
        self,
        project_layout: tuple[str, str, Path],
        capsys: pytest.CaptureFixture[str],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        project_name, _, primary = project_layout
        adj = self._make_adjacent(primary, 15)
        migrate_args = make_args(
            workspace_subcommand="migrate",
            project=project_name,
            to="xdg-state",
            symlink_transition=True,
            finalize=False,
            dry_run=False,
        )
        with pytest.raises(SystemExit):
            handle_workspace_command(migrate_args)
        capsys.readouterr()
        assert adj.is_symlink()

        # Cleanup is wired against the configured store (absolute policy
        # via the fixture).  Re-point the handler at the same managed
        # root the migration just populated so cleanup sees registry #15.
        target_store = WorkspaceStore(
            str(primary),
            config={
                "workspace": {
                    "root": "xdg-state",
                    "project_key": "demo-key",
                }
            },
        )
        managed = Path(target_store.resolve(15).checkout_dir.rstrip("/"))
        managed_root = managed.parent
        cleanup_config = {
            "workspace": {
                "root": str(managed_root),
                "project_key": "demo-key",
                "cleanup_ttl_days": 1,
            }
        }
        monkeypatch.setattr(
            "sase.main.workspace_handler.load_merged_config",
            lambda: cleanup_config,
        )
        monkeypatch.setattr(
            "sase.config.core.load_merged_config",
            lambda: cleanup_config,
        )

        # Force the entry stale and tell cleanup it has no active claims.
        registry = load_or_init_registry(target_store)
        registry.workspaces["15"].last_used_at = time.time() - 5 * 86400
        save_registry(target_store, registry)

        cleanup_store = WorkspaceStore(str(primary), config=cleanup_config)
        cleanup_registry = load_or_init_registry(cleanup_store)
        cleanup_registry.workspaces["15"] = registry.workspaces["15"]
        save_registry(cleanup_store, cleanup_registry)

        args = make_args(
            workspace_subcommand="cleanup",
            project=project_name,
            stale=True,
            include_shares=False,
            dry_run=False,
        )
        with pytest.raises(SystemExit) as exc:
            handle_workspace_command(args)
        assert exc.value.code == 0
        out = capsys.readouterr().out
        assert "removing #15" in out
        assert "removed transition symlink" in out
        assert not adj.exists()
        assert not managed.exists()

    def test_migrate_requires_to_or_finalize(
        self,
        project_layout: tuple[str, str, Path],
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        project_name, _, _ = project_layout
        args = make_args(
            workspace_subcommand="migrate",
            project=project_name,
            to=None,
            symlink_transition=False,
            finalize=False,
            dry_run=False,
        )
        with pytest.raises(SystemExit) as exc:
            handle_workspace_command(args)
        assert exc.value.code == 2
        assert "--to" in capsys.readouterr().err
