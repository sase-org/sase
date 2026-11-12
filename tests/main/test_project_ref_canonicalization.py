"""Regression: -p accepts key, display name, or alias (sase-zo)."""

from __future__ import annotations

import argparse
from pathlib import Path

import pytest

from sase.main import workspace_handler as workspace_commands
from sase.main.workspace_handler_context import (
    _canonicalize_project_ref,
    resolve_project_context,
)
from sase.core.project_lifecycle_facade import (
    apply_project_lifecycle_update,
    read_project_lifecycle_from_content,
)


def _write_projects_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> tuple[Path, Path]:
    home = tmp_path / "home"
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.delenv("XDG_STATE_HOME", raising=False)
    monkeypatch.delenv("SASE_WORKSPACE_ROOT", raising=False)
    projects_root = home / ".sase" / "projects"
    primary = tmp_path / "primary"
    primary.mkdir(parents=True, exist_ok=True)
    fake_config = {"workspace": {"root": str(tmp_path / "managed")}}
    monkeypatch.setattr(
        "sase.main.workspace_handler.load_merged_config", lambda: fake_config
    )
    monkeypatch.setattr("sase.config.core.load_merged_config", lambda: fake_config)
    return projects_root, primary


def _write_project(
    projects_root: Path,
    key: str,
    primary: Path,
    *,
    display: str | None = None,
    aliases: str | None = None,
) -> Path:
    project_dir = projects_root / key
    project_dir.mkdir(parents=True, exist_ok=True)
    lines = [f"WORKSPACE_DIR: {primary}\n"]
    if display is not None:
        lines.append(f"PROJECT_NAME: {display}\n")
    if aliases is not None:
        lines.append(f"PROJECT_ALIASES: {aliases}\n")
    project_file = project_dir / f"{key}.sase"
    project_file.write_text("".join(lines), encoding="utf-8")
    return project_file


def _resolve(project: str | None):
    return resolve_project_context(
        project,
        load_config=lambda: {"workspace": {"root": "/tmp/managed"}},
        read_project_lifecycle=read_project_lifecycle_from_content,
        apply_project_lifecycle=apply_project_lifecycle_update,
    )


def test_canonicalize_accepts_key_display_alias_and_casefold(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    projects_root, primary = _write_projects_root(tmp_path, monkeypatch)
    _write_project(
        projects_root, "gh_acme__widgets", primary, display="widgets", aliases="wdg"
    )

    assert _canonicalize_project_ref("gh_acme__widgets") == "gh_acme__widgets"
    assert _canonicalize_project_ref("widgets") == "gh_acme__widgets"
    assert _canonicalize_project_ref("WIDGETS") == "gh_acme__widgets"
    assert _canonicalize_project_ref("wdg") == "gh_acme__widgets"
    assert _canonicalize_project_ref("WDG") == "gh_acme__widgets"

    ctx = _resolve("widgets")
    assert ctx.project_name == "gh_acme__widgets"
    assert ctx.project_file.endswith("gh_acme__widgets.sase")
    ctx = _resolve("WDG")
    assert ctx.project_name == "gh_acme__widgets"
    ctx = _resolve("gh_acme__widgets")
    assert ctx.project_name == "gh_acme__widgets"


def test_registered_project_wins_over_stray_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    projects_root, primary = _write_projects_root(tmp_path, monkeypatch)
    _write_project(
        projects_root, "gh_acme__sase", primary, display="sase", aliases=None
    )
    stray_dir = projects_root / "sase"
    stray_dir.mkdir(parents=True, exist_ok=True)
    (stray_dir / "sase.sase").write_text("NAME: stray\n", encoding="utf-8")

    ctx = _resolve("sase")
    assert ctx.project_name == "gh_acme__sase"
    assert "gh_acme__sase.sase" in ctx.project_file


def test_ambiguous_display_exits_two_with_candidates(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    projects_root, primary = _write_projects_root(tmp_path, monkeypatch)
    _write_project(projects_root, "gh_acme__aaa", primary, display="dup")
    _write_project(projects_root, "gh_acme__bbb", primary, display="dup")

    with pytest.raises(SystemExit) as exc:
        _canonicalize_project_ref("dup")
    assert exc.value.code == 2
    err = capsys.readouterr().err
    assert "gh_acme__aaa" in err
    assert "gh_acme__bbb" in err
    assert "dup" in err


def test_workspace_list_accepts_display_name(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    projects_root, primary = _write_projects_root(tmp_path, monkeypatch)
    _write_project(
        projects_root, "gh_acme__widgets", primary, display="widgets", aliases="wdg"
    )

    for ref in ("gh_acme__widgets", "widgets", "wdg", "WIDGETS"):
        args = argparse.Namespace(workspace_subcommand="list", project=ref, json=True)
        with pytest.raises(SystemExit) as exc:
            workspace_commands.handle_workspace_command(args)
        assert exc.value.code == 0
        capsys.readouterr()


def test_repo_list_accepts_display_name(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from sase.main import repo_handler as repo_commands
    from sase.main.parser import create_parser
    from sase.repo_inventory import RepoInventory

    projects_root, primary = _write_projects_root(tmp_path, monkeypatch)
    _write_project(
        projects_root, "gh_acme__widgets", primary, display="widgets", aliases="wdg"
    )
    monkeypatch.setattr(
        "sase.main.repo_handler.collect_repo_inventory",
        lambda **_kwargs: RepoInventory(()),
    )

    for ref in ("gh_acme__widgets", "widgets", "wdg"):
        args = create_parser().parse_args(["repo", "list", "-p", ref])
        with pytest.raises(SystemExit) as exc:
            repo_commands.handle_repo_command(args)
        assert exc.value.code == 0
        capsys.readouterr()


def test_repo_path_accepts_display_name(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from sase.main import repo_handler as repo_commands
    from sase.main.parser import create_parser
    from sase.repo_inventory import RepoCloneRecord, RepoInventory
    from tests.main.repo_handler_helpers import repo_record

    projects_root, primary = _write_projects_root(tmp_path, monkeypatch)
    _write_project(
        projects_root, "gh_acme__widgets", primary, display="widgets", aliases="wdg"
    )
    record = repo_record(
        tmp_path,
        name="side",
        kind="sidecar",
        project="gh_acme__widgets",
        clones=(RepoCloneRecord(0, str(primary / "side"), True),),
    )
    (primary / "side").mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(
        "sase.main.repo_handler.collect_repo_inventory",
        lambda **_kwargs: RepoInventory((record,)),
    )

    for ref in ("widgets", "wdg", "gh_acme__widgets"):
        args = create_parser().parse_args(["repo", "path", "side", "-p", ref])
        with pytest.raises(SystemExit) as exc:
            repo_commands.handle_repo_command(args)
        assert exc.value.code == 0
        out = capsys.readouterr().out
        assert "side" in out


def test_repo_open_accepts_display_name(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from sase.main import repo_handler as repo_commands
    from sase.main.parser import create_parser
    from sase.repo_inventory import RepoInventory
    from tests.main.repo_handler_helpers import repo_record

    projects_root, primary = _write_projects_root(tmp_path, monkeypatch)
    _write_project(
        projects_root, "gh_acme__widgets", primary, display="widgets", aliases="wdg"
    )
    sidecar = repo_record(
        tmp_path, name="research", kind="sidecar", project="gh_acme__widgets"
    )
    opened: list[str] = []
    monkeypatch.setattr(
        "sase.main.repo_handler.collect_repo_inventory",
        lambda **_kwargs: RepoInventory((sidecar,)),
    )
    monkeypatch.setattr(
        "sase.main.workspace_handler_list.prepare_opened_checkout",
        lambda ctx, *_args, **_kwargs: opened.append(ctx.project_name) or sidecar.path,
    )
    monkeypatch.setattr(
        "sase.main.repo_handler._record_repo_open", lambda **_kwargs: None
    )

    for ref in ("widgets", "wdg", "gh_acme__widgets"):
        opened.clear()
        args = create_parser().parse_args(
            ["repo", "open", "research", "-p", ref, "-r", "Need reports", "-w", "0"]
        )
        with pytest.raises(SystemExit) as exc:
            repo_commands.handle_repo_command(args)
        assert exc.value.code == 0
        assert opened
        capsys.readouterr()
