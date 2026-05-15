"""Tests for the ``sase workspace`` parser and handler (Phase 7 of sase-3p)."""

from __future__ import annotations

import argparse
import json
import os
import time
from pathlib import Path
from unittest.mock import patch

import pytest

from sase.main.parser import create_parser
from sase.main.workspace_handler import handle_workspace_command
from sase.running_field._model import WorkspaceClaim
from sase.workspace_provider.registry import (
    load_or_init_registry,
    record_workspace,
    save_registry,
)
from sase.workspace_provider.store import WorkspaceStore


@pytest.fixture
def project_layout(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> tuple[str, str, Path]:
    """Set up a fake project rooted under ``~/.sase/projects/<name>``.

    Returns ``(project_name, project_file, primary_workspace_dir)``.  Uses
    an absolute managed root so the registry-backed code paths are
    exercised end-to-end.
    """
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.delenv("XDG_STATE_HOME", raising=False)
    monkeypatch.delenv("SASE_WORKSPACE_ROOT", raising=False)
    sase_dir = tmp_path / "home" / ".sase" / "projects"
    primary = tmp_path / "primary"
    primary.mkdir()
    project_name = "demo"
    project_dir = sase_dir / project_name
    project_dir.mkdir(parents=True)
    project_file = project_dir / f"{project_name}.sase"
    project_file.write_text(f"WORKSPACE_DIR: {primary}\n", encoding="utf-8")

    managed_root = tmp_path / "managed"
    fake_config = {
        "workspace": {
            "root": str(managed_root),
            "project_key": "demo-key",
            "cleanup_ttl_days": 1,
        }
    }
    monkeypatch.setattr(
        "sase.main.workspace_handler.load_merged_config",
        lambda: fake_config,
    )
    monkeypatch.setattr(
        "sase.config.core.load_merged_config",
        lambda: fake_config,
    )
    return project_name, str(project_file), primary


def _make_args(**overrides: object) -> argparse.Namespace:
    return argparse.Namespace(**overrides)


# ── parser dispatch ────────────────────────────────────────────────


class TestParser:
    def test_list_dispatch(self) -> None:
        ns = create_parser().parse_args(["workspace", "list", "-p", "demo", "-j"])
        assert ns.command == "workspace"
        assert ns.workspace_subcommand == "list"
        assert ns.project == "demo"
        assert ns.json is True

    def test_path_requires_number(self) -> None:
        with pytest.raises(SystemExit):
            create_parser().parse_args(["workspace", "path"])

    def test_cleanup_options(self) -> None:
        ns = create_parser().parse_args(
            ["workspace", "cleanup", "-s", "-i", "-n", "-p", "demo"]
        )
        assert ns.workspace_subcommand == "cleanup"
        assert ns.stale is True
        assert ns.include_shares is True
        assert ns.dry_run is True

    def test_repair_dry_run(self) -> None:
        ns = create_parser().parse_args(["workspace", "repair", "-n"])
        assert ns.workspace_subcommand == "repair"
        assert ns.dry_run is True

    def test_unknown_subcommand_exits(self, capsys: pytest.CaptureFixture[str]) -> None:
        args = _make_args(workspace_subcommand=None)
        with pytest.raises(SystemExit) as exc:
            handle_workspace_command(args)
        assert exc.value.code == 2
        assert "Usage" in capsys.readouterr().err


# ── list ───────────────────────────────────────────────────────────


class TestList:
    def test_human_list_shows_primary(
        self,
        project_layout: tuple[str, str, Path],
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        project_name, _, _ = project_layout
        args = _make_args(workspace_subcommand="list", project=project_name, json=False)
        with pytest.raises(SystemExit) as exc:
            handle_workspace_command(args)
        assert exc.value.code == 0
        out = capsys.readouterr().out
        assert f"Project: {project_name}" in out
        assert "policy=absolute" in out
        # Primary checkout appears with role=primary
        assert "primary" in out

    def test_json_list_includes_registered_workspace(
        self,
        project_layout: tuple[str, str, Path],
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        project_name, _, primary = project_layout
        store = WorkspaceStore(
            str(primary),
            config={
                "workspace": {
                    "root": str(primary.parent / "managed"),
                    "project_key": "demo-key",
                }
            },
        )
        record_workspace(store, store.resolve(10), role="claim")

        args = _make_args(workspace_subcommand="list", project=project_name, json=True)
        with pytest.raises(SystemExit):
            handle_workspace_command(args)
        payload = json.loads(capsys.readouterr().out)
        nums = {row["workspace_num"] for row in payload["workspaces"]}
        assert 0 in nums
        assert 10 in nums
        assert payload["project"] == project_name
        assert payload["root_policy"] == "absolute"


# ── path ───────────────────────────────────────────────────────────


class TestPath:
    def test_path_zero_prints_primary(
        self,
        project_layout: tuple[str, str, Path],
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        project_name, _, primary = project_layout
        args = _make_args(
            workspace_subcommand="path", project=project_name, workspace_num=0
        )
        with pytest.raises(SystemExit) as exc:
            handle_workspace_command(args)
        assert exc.value.code == 0
        # Primary path is printed (resolution strips trailing slash).
        assert str(primary).rstrip("/") in capsys.readouterr().out

    def test_path_registered_managed_workspace(
        self,
        project_layout: tuple[str, str, Path],
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        project_name, _, primary = project_layout
        store = WorkspaceStore(
            str(primary),
            config={
                "workspace": {
                    "root": str(primary.parent / "managed"),
                    "project_key": "demo-key",
                }
            },
        )
        wp = store.resolve(10)
        # Pretend the checkout already exists on disk so ``path`` returns
        # the materialized location without invoking ``git clone``.
        managed_dir = wp.checkout_dir.rstrip("/")
        os.makedirs(managed_dir, exist_ok=True)
        # Trick ensure_git_clone_at's "still valid" check into accepting
        # the directory by writing a .git directory.
        os.makedirs(os.path.join(managed_dir, ".git"), exist_ok=True)
        with patch("sase.workspace_provider.utils.subprocess.run") as mock_run:
            mock_run.return_value.returncode = 0
            record_workspace(store, wp, role="claim")
            args = _make_args(
                workspace_subcommand="path",
                project=project_name,
                workspace_num=10,
            )
            with pytest.raises(SystemExit) as exc:
                handle_workspace_command(args)
        assert exc.value.code == 0
        out = capsys.readouterr().out.strip()
        assert out == managed_dir

    def test_path_unregistered_does_not_materialize(
        self,
        project_layout: tuple[str, str, Path],
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        project_name, _, primary = project_layout
        args = _make_args(
            workspace_subcommand="path", project=project_name, workspace_num=42
        )
        with pytest.raises(SystemExit) as exc:
            handle_workspace_command(args)
        assert exc.value.code == 0
        out = capsys.readouterr().out.strip()
        # Resolved path is printed but no clone was performed.
        assert "_42" in out
        assert not os.path.isdir(out)


# ── cleanup ────────────────────────────────────────────────────────


class TestCleanup:
    def test_dry_run_reports_without_deleting(
        self,
        project_layout: tuple[str, str, Path],
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        project_name, _, primary = project_layout
        store = WorkspaceStore(
            str(primary),
            config={
                "workspace": {
                    "root": str(primary.parent / "managed"),
                    "project_key": "demo-key",
                    "cleanup_ttl_days": 1,
                }
            },
        )
        wp = store.resolve(10)
        managed = wp.checkout_dir.rstrip("/")
        os.makedirs(managed, exist_ok=True)
        record_workspace(store, wp, role="claim")
        # Force the entry to be stale (older than 1 day).
        registry = load_or_init_registry(store)
        registry.workspaces["10"].last_used_at = time.time() - 2 * 86400
        save_registry(store, registry)

        args = _make_args(
            workspace_subcommand="cleanup",
            project=project_name,
            stale=True,
            include_shares=False,
            dry_run=True,
        )
        with pytest.raises(SystemExit) as exc:
            handle_workspace_command(args)
        assert exc.value.code == 0
        out = capsys.readouterr().out
        assert "would remove #10" in out
        # Filesystem untouched.
        assert os.path.isdir(managed)
        # Registry unchanged.
        reloaded = load_or_init_registry(store)
        assert "10" in reloaded.workspaces

    def test_cleanup_skips_active_claims(
        self,
        project_layout: tuple[str, str, Path],
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        project_name, _, primary = project_layout
        store = WorkspaceStore(
            str(primary),
            config={
                "workspace": {
                    "root": str(primary.parent / "managed"),
                    "project_key": "demo-key",
                    "cleanup_ttl_days": 1,
                }
            },
        )
        record_workspace(store, store.resolve(10), role="claim")
        registry = load_or_init_registry(store)
        registry.workspaces["10"].last_used_at = time.time() - 2 * 86400
        save_registry(store, registry)

        claim = WorkspaceClaim(workspace_num=10, workflow="axe", cl_name=None, pid=123)
        with patch(
            "sase.main.workspace_handler.get_claimed_workspaces",
            return_value=[claim],
        ):
            args = _make_args(
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
        assert "No stale managed checkouts" in out

    def test_cleanup_without_stale_flag_errors(
        self,
        project_layout: tuple[str, str, Path],
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        project_name, _, _ = project_layout
        args = _make_args(
            workspace_subcommand="cleanup",
            project=project_name,
            stale=False,
            include_shares=False,
            dry_run=False,
        )
        with pytest.raises(SystemExit) as exc:
            handle_workspace_command(args)
        assert exc.value.code == 2
        assert "--stale" in capsys.readouterr().err


# ── repair ─────────────────────────────────────────────────────────


class TestRepair:
    def test_repair_drops_missing_entries(
        self,
        project_layout: tuple[str, str, Path],
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        project_name, _, primary = project_layout
        store = WorkspaceStore(
            str(primary),
            config={
                "workspace": {
                    "root": str(primary.parent / "managed"),
                    "project_key": "demo-key",
                }
            },
        )
        wp = store.resolve(10)
        # Register without ever creating the checkout directory.
        record_workspace(store, wp, role="claim")
        assert not os.path.isdir(wp.checkout_dir.rstrip("/"))

        args = _make_args(
            workspace_subcommand="repair",
            project=project_name,
            dry_run=False,
        )
        with pytest.raises(SystemExit) as exc:
            handle_workspace_command(args)
        assert exc.value.code == 0
        out = capsys.readouterr().out
        assert "dropping stale registry entry for #10" in out

        reloaded = load_or_init_registry(store)
        assert "10" not in reloaded.workspaces

    def test_repair_dry_run_does_not_modify_registry(
        self,
        project_layout: tuple[str, str, Path],
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        project_name, _, primary = project_layout
        store = WorkspaceStore(
            str(primary),
            config={
                "workspace": {
                    "root": str(primary.parent / "managed"),
                    "project_key": "demo-key",
                }
            },
        )
        record_workspace(store, store.resolve(10), role="claim")

        args = _make_args(
            workspace_subcommand="repair",
            project=project_name,
            dry_run=True,
        )
        with pytest.raises(SystemExit) as exc:
            handle_workspace_command(args)
        assert exc.value.code == 0
        out = capsys.readouterr().out
        assert "would drop" in out

        reloaded = load_or_init_registry(store)
        assert "10" in reloaded.workspaces


# ── migrate ────────────────────────────────────────────────────────


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

        args = _make_args(
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

    def test_migrate_with_symlink_transition_creates_symlink(
        self,
        project_layout: tuple[str, str, Path],
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        project_name, _, primary = project_layout
        adj = self._make_adjacent(primary, 11)

        args = _make_args(
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

        args = _make_args(
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

        args = _make_args(
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
        migrate_args = _make_args(
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
        finalize_args = _make_args(
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
        migrate_args = _make_args(
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

        args = _make_args(
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
        args = _make_args(
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


# ── project resolution ─────────────────────────────────────────────


class TestProjectResolution:
    def test_missing_project_inference_exits(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        # Empty home with no projects directory and stub the inference
        # to ensure we don't accidentally pick up the dev's real projects.
        monkeypatch.setenv("HOME", str(tmp_path))
        monkeypatch.chdir(tmp_path)
        monkeypatch.setattr(
            "sase.bead.project_name.infer_project_name_from_cwd",
            lambda cwd=None: None,
        )
        args = _make_args(workspace_subcommand="list", project=None, json=False)
        with pytest.raises(SystemExit) as exc:
            handle_workspace_command(args)
        assert exc.value.code == 2
        assert "infer project" in capsys.readouterr().err
