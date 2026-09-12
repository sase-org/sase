"""Workspace behavior tests for ``sase repo open``."""

from __future__ import annotations

from pathlib import Path
import subprocess
from unittest.mock import patch

import pytest

from sase.linked_repos import opened_linked_repo_records
from sase.main.parser import create_parser
from sase.main.repo_handler import (
    _repo_target_context,
    _resolve_open_workspace_num,
    handle_repo_command,
)
from sase.main.workspace_handler import handle_workspace_command
from sase.main.workspace_handler_context import ProjectContext
from sase.repo_inventory import RepoCloneRecord, RepoInventory, RepoRecord
from sase.repo_open_log import read_repo_open_events
from sase.workspace_provider.marker import CheckoutMarker
from sase.workspace_provider.store import WorkspaceStore
from tests.main.repo_handler_helpers import project_context, repo_record


def test_repo_reopen_preserves_dirty_tracked_and_untracked_checkout(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    home = tmp_path / "home"
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("SASE_HOME", str(home / ".sase"))
    host_ctx = project_context(tmp_path)
    primary = Path(host_ctx.primary_workspace_dir)
    subprocess.run(["git", "init", "-q"], cwd=primary, check=True)
    subprocess.run(["git", "config", "user.name", "SASE Test"], cwd=primary, check=True)
    subprocess.run(
        ["git", "config", "user.email", "sase-test@example.invalid"],
        cwd=primary,
        check=True,
    )
    tracked = primary / "tracked.txt"
    tracked.write_text("clean\n", encoding="utf-8")
    subprocess.run(["git", "add", "tracked.txt"], cwd=primary, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "initial"], cwd=primary, check=True)
    inventory = RepoInventory((repo_record(tmp_path, name="demo", kind="primary"),))

    monkeypatch.setattr(
        "sase.main.workspace_handler._resolve_project_context",
        lambda _project: host_ctx,
    )
    monkeypatch.setattr(
        "sase.main.repo_handler.collect_repo_inventory",
        lambda **_kwargs: inventory,
    )
    monkeypatch.setattr(
        "sase.main.workspace_handler._resolve_checkout_path",
        lambda _ctx, _workspace, *, materialize: str(primary),
    )
    monkeypatch.setattr(
        "sase.sdd.files.ensure_bare_git_sdd_initialized",
        lambda *_args, **_kwargs: None,
    )

    def fail_prepare(*_args: object, **_kwargs: object) -> bool:
        raise AssertionError("repo open must not run runner workspace preparation")

    monkeypatch.setattr("sase.axe.runner_workspace.prepare_workspace", fail_prepare)
    args = create_parser().parse_args(
        ["repo", "open", "demo", "-p", "demo", "-r", "inspect checkout", "-w", "0"]
    )

    with pytest.raises(SystemExit) as first_exit:
        handle_repo_command(args)
    assert first_exit.value.code == 0
    assert capsys.readouterr().out == f"{primary}\n"

    tracked.write_text("dirty tracked\n", encoding="utf-8")
    untracked = primary / "untracked.txt"
    untracked.write_text("dirty untracked\n", encoding="utf-8")
    with pytest.raises(SystemExit) as second_exit:
        handle_repo_command(args)

    assert second_exit.value.code == 0
    assert capsys.readouterr().out == f"{primary}\n"
    assert tracked.read_text(encoding="utf-8") == "dirty tracked\n"
    assert untracked.read_text(encoding="utf-8") == "dirty untracked\n"
    events = read_repo_open_events(project="demo")
    assert len(events) == 2
    assert {event.path for event in events} == {str(primary)}


def test_workspace_inference_uses_matching_checkout_marker(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    host_ctx = project_context(tmp_path)
    marker = CheckoutMarker(
        project_name="demo",
        project_key="demo",
        workspace_num=12,
        primary_workspace_dir=host_ctx.primary_workspace_dir,
        registry_path=str(tmp_path / "registry.json"),
    )
    monkeypatch.setattr(
        "sase.main.repo_handler.find_marker_from_cwd",
        lambda _cwd: (str(tmp_path), marker),
    )

    assert _resolve_open_workspace_num(host_ctx, None, cwd=tmp_path) == 12


def test_workspace_inference_treats_primary_checkout_as_zero(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    host_ctx = project_context(tmp_path)
    cwd = Path(host_ctx.primary_workspace_dir) / "src"
    cwd.mkdir()
    monkeypatch.setattr(
        "sase.main.repo_handler.find_marker_from_cwd",
        lambda _cwd: None,
    )

    assert _resolve_open_workspace_num(host_ctx, None, cwd=cwd) == 0


def test_repo_open_skips_runner_prepare_while_legacy_alias_keeps_it(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    home = tmp_path / "home"
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("SASE_ARTIFACTS_DIR", str(tmp_path / "artifacts"))
    monkeypatch.setenv("SASE_AGENT_NAME", "phase-one")

    host_primary = tmp_path / "demo"
    linked_primary = tmp_path / "core"
    host_primary.mkdir()
    linked_primary.mkdir()
    project_dir = home / ".sase" / "projects" / "demo"
    project_dir.mkdir(parents=True)
    project_file = project_dir / "demo.sase"
    project_file.write_text(
        f"WORKSPACE_DIR: {host_primary}\n",
        encoding="utf-8",
    )
    host_ctx = ProjectContext(
        project_name="demo",
        project_file=str(project_file),
        primary_workspace_dir=str(host_primary),
        store=WorkspaceStore(str(host_primary)),
    )
    linked_ctx = ProjectContext(
        project_name="core",
        project_file=str(home / ".sase" / "projects" / "core" / "core.sase"),
        primary_workspace_dir=str(linked_primary),
        store=WorkspaceStore(str(linked_primary)),
        is_sibling=True,
        is_configured_linked_repo=True,
        linked_host_primary_workspace_dir=str(host_primary),
    )
    linked = RepoRecord(
        name="core",
        kind="linked",
        project="demo",
        project_key="demo",
        path=str(linked_primary),
        exists=True,
        auto_clone=False,
        description=None,
        source="linked_repos config",
        env_name="CORE",
    )
    checkout = str(tmp_path / "demo_12" / "sase" / "repos" / "linked" / "core")

    def resolve_context(project: str | None) -> ProjectContext:
        return linked_ctx if project == "core" else host_ctx

    def prepare_workspace_with_progress(*_args: object, **_kwargs: object) -> bool:
        print("Cleaning workspace...")
        return True

    with (
        patch(
            "sase.main.workspace_handler._resolve_project_context",
            side_effect=resolve_context,
        ),
        patch(
            "sase.main.repo_handler.collect_repo_inventory",
            return_value=RepoInventory((linked,)),
        ),
        patch("sase.main.repo_handler.load_merged_config", return_value={}),
        patch("sase.sdd.files.ensure_bare_git_sdd_initialized"),
        patch(
            "sase.main.workspace_handler._resolve_checkout_path",
            return_value=checkout,
        ),
        patch(
            "sase.axe.runner_workspace.prepare_workspace",
            side_effect=prepare_workspace_with_progress,
        ) as prepare_workspace,
    ):
        new_args = create_parser().parse_args(
            ["repo", "open", "core", "-p", "demo", "-r", "same reason", "-w", "12"]
        )
        with pytest.raises(SystemExit) as new_exit:
            handle_repo_command(new_args)
        new_output = capsys.readouterr()

        legacy_args = create_parser().parse_args(
            ["workspace", "open", "-p", "core", "-r", "same reason", "12"]
        )
        with pytest.raises(SystemExit) as legacy_exit:
            handle_workspace_command(legacy_args)
        legacy_output = capsys.readouterr()

    assert new_exit.value.code == 0
    assert new_output.out == f"{checkout}\n"
    assert "Cleaning workspace..." not in new_output.err
    assert legacy_exit.value.code == 0
    assert legacy_output.out == f"{checkout}\n"
    assert "Cleaning workspace..." in legacy_output.err
    assert "deprecated" in legacy_output.err
    assert prepare_workspace.call_count == 1

    events = read_repo_open_events(project="demo")
    assert len(events) == 2
    comparable = [
        (
            event.project,
            event.repo,
            event.repo_kind,
            event.workspace_num,
            event.path,
            event.agent_name,
            event.reason,
        )
        for event in events
    ]
    assert comparable[0] == comparable[1]
    marker = opened_linked_repo_records(tmp_path / "artifacts")["core"]
    assert marker["workspace_dir"] == checkout
    assert marker["reason"] == "same reason"


def test_repo_target_context_uses_durable_workspace_zero_clone(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    host_ctx = project_context(tmp_path)
    durable = tmp_path / "linked-primary"
    scoped = Path(host_ctx.primary_workspace_dir) / "sase" / "repos" / "linked" / "core"
    durable.mkdir()
    scoped.mkdir(parents=True)
    record = RepoRecord(
        name="core",
        kind="linked",
        project="demo",
        project_key="demo",
        path=str(scoped),
        exists=True,
        auto_clone=False,
        description=None,
        source="test",
        env_name="CORE",
        clones=(
            RepoCloneRecord(0, str(durable), True),
            RepoCloneRecord(10, str(scoped), True),
        ),
    )
    monkeypatch.setattr(
        "sase.main.repo_handler.load_merged_config",
        lambda: {"workspace": {"root": "adjacent"}},
    )

    target_ctx = _repo_target_context(host_ctx, record)

    assert target_ctx.primary_workspace_dir == str(durable)
    assert target_ctx.store.primary_workspace_dir == str(durable)
    assert (
        target_ctx.linked_host_primary_workspace_dir == host_ctx.primary_workspace_dir
    )
