"""Tests for ``sase workspace cleanup`` and ``sase workspace repair``."""

from __future__ import annotations

import os
import time
from pathlib import Path
from unittest.mock import patch

import pytest

from sase.main.workspace_handler import handle_workspace_command
from sase.running_field._model import WorkspaceClaim
from sase.workspace_provider.registry import (
    load_or_init_registry,
    record_workspace,
    save_registry,
)
from sase.workspace_provider.store import WorkspaceStore
from tests.main.workspace_handler_helpers import make_args, project_layout

__all__ = ["project_layout"]


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

        args = make_args(
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
        assert "No stale managed checkouts" in out

    def test_cleanup_without_stale_flag_errors(
        self,
        project_layout: tuple[str, str, Path],
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        project_name, _, _ = project_layout
        args = make_args(
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

        args = make_args(
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

        args = make_args(
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
