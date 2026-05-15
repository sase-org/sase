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
