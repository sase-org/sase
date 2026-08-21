"""Tests for chezmoi-managed completion deployment."""

from __future__ import annotations

import json
from pathlib import Path

from sase.completion.deploy_chezmoi import (
    _build_chezmoi_completion_plan,
    deploy_chezmoi_completion,
)
from sase.main.parser import create_parser


def test_build_plan_maps_scripts_and_stamps_to_chezmoi_source(tmp_path: Path) -> None:
    home = tmp_path / "home"
    source = tmp_path / "chezmoi" / "home"

    plan = _build_chezmoi_completion_plan(
        source_root=source,
        home=home,
        version="0.16.0",
        timestamp="2026-08-21T12:00:00Z",
    )

    source_paths = {file.source.relative_to(source).as_posix() for file in plan.files}
    assert source_paths == {
        "dot_config/fish/completions/sase.fish",
        "dot_local/share/bash-completion/completions/sase",
        "dot_zfunc/_sase",
    }

    stamp_by_shell = {file.shell: file for file in plan.stamp_files}
    zsh_stamp = json.loads(stamp_by_shell["zsh"].text)
    assert zsh_stamp["owner"] == "chezmoi"
    assert zsh_stamp["target"] == str(home / ".zfunc" / "_sase")
    assert stamp_by_shell["zsh"].source.relative_to(source).as_posix() == (
        "dot_sase/completion/stamp/zsh.json"
    )


def test_deploy_dry_run_is_read_only(tmp_path: Path) -> None:
    source = tmp_path / "chezmoi" / "home"

    result = deploy_chezmoi_completion(dry_run=True, source_root=source)

    assert result.exit_code == 0
    assert result.written_paths == ()
    assert not source.exists()


def test_deploy_writes_files_and_delegates_chezmoi(tmp_path: Path) -> None:
    home = tmp_path / "home"
    source = tmp_path / "chezmoi" / "home"
    calls: list[tuple[tuple[Path, ...], object]] = []

    def fake_deploy(paths: tuple[Path, ...], behavior: object) -> int:
        calls.append((paths, behavior))
        return 0

    result = deploy_chezmoi_completion(
        source_root=source,
        home=home,
        deploy_fn=fake_deploy,
    )

    assert result.exit_code == 0
    assert calls and calls[0][0] == result.plan.paths
    for path in result.plan.paths:
        assert path.is_file()
    behavior = calls[0][1]
    assert behavior.command_label == "completion deploy-chezmoi"
    assert behavior.chezmoi_home == source


def test_deploy_parser_exposes_sorted_controls() -> None:
    args = create_parser().parse_args(
        [
            "completion",
            "deploy-chezmoi",
            "-a",
            "-c",
            "-d",
            "-n",
            "-s",
            "/tmp/source",
        ]
    )

    assert args.completion_subcommand == "deploy-chezmoi"
    assert args.no_apply is True
    assert args.no_commit is True
    assert args.dry_run is True
    assert args.no_push is True
    assert args.source == "/tmp/source"
