"""Tests for ``sase workspace cleanup`` and ``sase workspace repair``."""

from __future__ import annotations

import json
import os
import subprocess
import time
from pathlib import Path
from unittest.mock import patch

import pytest

from sase.main.workspace_handler import handle_workspace_command
from sase.running_field._model import WorkspaceClaim
from sase.workspace_provider.git_objects import ensure_sase_alternate, git_object_dir
from sase.workspace_provider.registry import (
    load_or_init_registry,
    record_workspace,
    save_registry,
)
from sase.workspace_provider.store import WorkspaceStore
from sase.workspace_provider.utils import non_interactive_git_env
from tests.main.workspace_handler_helpers import make_args, project_layout

__all__ = ["project_layout"]


def _git(cwd: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        check=True,
        env=non_interactive_git_env(),
        stdin=subprocess.DEVNULL,
    )
    return result.stdout.strip()


def _init_primary_repo(primary: Path, *, commits: int = 1) -> None:
    _git(primary, "init")
    _git(primary, "config", "user.email", "test@example.com")
    _git(primary, "config", "user.name", "Test User")
    for idx in range(commits):
        (primary / f"file-{idx}.txt").write_text(
            f"value {idx}\n" * 20,
            encoding="utf-8",
        )
        _git(primary, "add", f"file-{idx}.txt")
        _git(primary, "commit", "-m", f"commit {idx}")
    _git(primary, "repack", "-a", "-d")


def _clone_registered_workspace(
    primary: Path,
    store: WorkspaceStore,
    workspace_num: int,
) -> Path:
    wp = store.resolve(workspace_num)
    checkout = Path(wp.checkout_dir.rstrip("/"))
    checkout.parent.mkdir(parents=True, exist_ok=True)
    _git(primary.parent, "clone", "--no-hardlinks", str(primary), str(checkout))
    record_workspace(store, wp, role="claim")
    return checkout


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


class TestCompact:
    def test_compact_dry_run_reports_without_touching_alternate(
        self,
        project_layout: tuple[str, str, Path],
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        project_name, _, primary = project_layout
        _init_primary_repo(primary, commits=3)
        store = WorkspaceStore(
            str(primary),
            config={
                "workspace": {
                    "root": str(primary.parent / "managed"),
                    "project_key": "demo-key",
                }
            },
        )
        checkout = _clone_registered_workspace(primary, store, 10)

        args = make_args(
            workspace_subcommand="compact",
            project=project_name,
            dry_run=True,
        )
        with pytest.raises(SystemExit) as exc:
            handle_workspace_command(args)

        assert exc.value.code == 0
        out = capsys.readouterr().out
        assert "would compact #10" in out
        assert not (git_object_dir(str(checkout)) / "info" / "alternates").exists()

    def test_compact_apply_installs_alternate_and_reclaims_objects(
        self,
        project_layout: tuple[str, str, Path],
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        project_name, _, primary = project_layout
        _init_primary_repo(primary, commits=6)
        store = WorkspaceStore(
            str(primary),
            config={
                "workspace": {
                    "root": str(primary.parent / "managed"),
                    "project_key": "demo-key",
                }
            },
        )
        checkout = _clone_registered_workspace(primary, store, 10)
        before = sum(
            path.stat().st_size
            for path in git_object_dir(str(checkout)).rglob("*")
            if path.is_file()
        )

        args = make_args(
            workspace_subcommand="compact",
            project=project_name,
            dry_run=False,
        )
        with pytest.raises(SystemExit) as exc:
            handle_workspace_command(args)

        assert exc.value.code == 0
        out = capsys.readouterr().out
        assert "compacted #10" in out
        alternates = git_object_dir(str(checkout)) / "info" / "alternates"
        assert (
            alternates.read_text(encoding="utf-8")
            == f"{git_object_dir(str(primary))}\n"
        )
        _git(checkout, "fsck", "--connectivity-only")
        after = sum(
            path.stat().st_size
            for path in git_object_dir(str(checkout)).rglob("*")
            if path.is_file()
        )
        assert after < before

    def test_compact_skips_dirty_checkout(
        self,
        project_layout: tuple[str, str, Path],
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        project_name, _, primary = project_layout
        _init_primary_repo(primary, commits=2)
        store = WorkspaceStore(
            str(primary),
            config={
                "workspace": {
                    "root": str(primary.parent / "managed"),
                    "project_key": "demo-key",
                }
            },
        )
        checkout = _clone_registered_workspace(primary, store, 10)
        (checkout / "dirty.txt").write_text("dirty\n", encoding="utf-8")

        args = make_args(
            workspace_subcommand="compact",
            project=project_name,
            dry_run=False,
        )
        with pytest.raises(SystemExit) as exc:
            handle_workspace_command(args)

        assert exc.value.code == 0
        out = capsys.readouterr().out
        assert "skipped #10: dirty checkout" in out
        assert not (git_object_dir(str(checkout)) / "info" / "alternates").exists()

    def test_compact_can_target_one_registered_checkout(
        self,
        project_layout: tuple[str, str, Path],
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        project_name, _, primary = project_layout
        _init_primary_repo(primary, commits=2)
        store = WorkspaceStore(
            str(primary),
            config={
                "workspace": {
                    "root": str(primary.parent / "managed"),
                    "project_key": "demo-key",
                }
            },
        )
        checkout_10 = _clone_registered_workspace(primary, store, 10)
        checkout_11 = _clone_registered_workspace(primary, store, 11)

        args = make_args(
            workspace_subcommand="compact",
            project=project_name,
            workspace_nums=[11],
            dry_run=True,
        )
        with pytest.raises(SystemExit) as exc:
            handle_workspace_command(args)

        assert exc.value.code == 0
        out = capsys.readouterr().out
        assert "would compact #11" in out
        assert "#10" not in out
        assert not (git_object_dir(str(checkout_10)) / "info" / "alternates").exists()
        assert not (git_object_dir(str(checkout_11)) / "info" / "alternates").exists()

    def test_compact_json_reports_structured_dry_run_rows(
        self,
        project_layout: tuple[str, str, Path],
        capsys: pytest.CaptureFixture[str],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from sase.main import workspace_handler_maintenance as maintenance

        project_name, _, primary = project_layout
        _init_primary_repo(primary, commits=2)
        store = WorkspaceStore(
            str(primary),
            config={
                "workspace": {
                    "root": str(primary.parent / "managed"),
                    "project_key": "demo-key",
                }
            },
        )
        checkout = _clone_registered_workspace(primary, store, 10)
        monkeypatch.setattr(
            maintenance,
            "_compact_eligibility",
            lambda *_args, **_kwargs: maintenance._CompactEligibility(
                True,
                "eligible",
                before_bytes=4096,
                alternate_status="absent",
            ),
        )

        args = make_args(
            workspace_subcommand="compact",
            project=project_name,
            workspace_nums=[],
            dry_run=True,
            json=True,
        )
        with pytest.raises(SystemExit) as exc:
            handle_workspace_command(args)

        assert exc.value.code == 0
        payload = json.loads(capsys.readouterr().out)
        assert payload["apply"] is False
        assert payload["planned"] == 1
        assert payload["errors"] == 0
        assert payload["rows"][0]["status"] == "planned"
        assert payload["rows"][0]["workspace_num"] == 10
        assert payload["rows"][0]["checkout_dir"] == str(checkout)


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

    def test_repair_repoints_broken_sase_alternate(
        self,
        project_layout: tuple[str, str, Path],
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        project_name, _, primary = project_layout
        _init_primary_repo(primary, commits=3)
        store = WorkspaceStore(
            str(primary),
            config={
                "workspace": {
                    "root": str(primary.parent / "managed"),
                    "project_key": "demo-key",
                }
            },
        )
        checkout = _clone_registered_workspace(primary, store, 10)
        ensure_sase_alternate(str(primary), str(checkout))
        alternates = git_object_dir(str(checkout)) / "info" / "alternates"
        alternates.write_text(
            f"{primary.parent / 'missing-primary' / '.git' / 'objects'}\n",
            encoding="utf-8",
        )

        args = make_args(
            workspace_subcommand="repair",
            project=project_name,
            dry_run=False,
        )
        with pytest.raises(SystemExit) as exc:
            handle_workspace_command(args)

        assert exc.value.code == 0
        out = capsys.readouterr().out
        assert "repointing shared object alternate for #10" in out
        assert (
            alternates.read_text(encoding="utf-8")
            == f"{git_object_dir(str(primary))}\n"
        )
        _git(checkout, "fsck", "--connectivity-only")

    def test_repair_refuses_broken_non_sase_alternate(
        self,
        project_layout: tuple[str, str, Path],
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        project_name, _, primary = project_layout
        _init_primary_repo(primary, commits=3)
        store = WorkspaceStore(
            str(primary),
            config={
                "workspace": {
                    "root": str(primary.parent / "managed"),
                    "project_key": "demo-key",
                }
            },
        )
        checkout = _clone_registered_workspace(primary, store, 10)
        alternates = git_object_dir(str(checkout)) / "info" / "alternates"
        alternates.parent.mkdir(parents=True, exist_ok=True)
        original = f"{primary.parent / 'foreign-missing' / 'objects'}\n"
        alternates.write_text(original, encoding="utf-8")

        args = make_args(
            workspace_subcommand="repair",
            project=project_name,
            dry_run=False,
        )
        with pytest.raises(SystemExit) as exc:
            handle_workspace_command(args)

        assert exc.value.code == 1
        err = capsys.readouterr().err
        assert "failed #10: missing non-SASE alternate object dir" in err
        assert alternates.read_text(encoding="utf-8") == original

    def test_repair_dissociates_when_sharing_disabled(
        self,
        project_layout: tuple[str, str, Path],
        capsys: pytest.CaptureFixture[str],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        project_name, _, primary = project_layout
        _init_primary_repo(primary, commits=3)
        disabled_config = {
            "workspace": {
                "root": str(primary.parent / "managed"),
                "project_key": "demo-key",
                "share_git_objects": False,
            }
        }
        monkeypatch.setattr(
            "sase.main.workspace_handler.load_merged_config",
            lambda: disabled_config,
        )
        monkeypatch.setattr(
            "sase.config.core.load_merged_config",
            lambda: disabled_config,
        )
        store = WorkspaceStore(str(primary), config=disabled_config)
        checkout = _clone_registered_workspace(primary, store, 10)
        ensure_sase_alternate(str(primary), str(checkout))
        alternates = git_object_dir(str(checkout)) / "info" / "alternates"
        missing_objects = primary.parent / "missing-primary" / ".git" / "objects"
        alternates.write_text(f"{missing_objects}\n", encoding="utf-8")
        _git(
            checkout,
            "config",
            "--local",
            "sase.workspaceGitObjectsPrimary",
            str(missing_objects),
        )
        assert alternates.exists()

        args = make_args(
            workspace_subcommand="repair",
            project=project_name,
            dry_run=False,
        )
        with pytest.raises(SystemExit) as exc:
            handle_workspace_command(args)

        assert exc.value.code == 0
        out = capsys.readouterr().out
        assert "dissociating shared object alternate for #10" in out
        assert not alternates.exists()
        _git(checkout, "fsck", "--connectivity-only")
