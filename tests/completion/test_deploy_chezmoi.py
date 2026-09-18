"""Tests for chezmoi-managed completion deployment."""

from __future__ import annotations

from pathlib import Path

from sase.completion.deploy_chezmoi import (
    _build_chezmoi_completion_plan,
    deploy_chezmoi_completion,
)
from sase.completion.loader import emit_loader
from sase.main.parser import create_parser


def test_build_plan_maps_loaders_and_stamp_removals_to_chezmoi_source(
    tmp_path: Path,
) -> None:
    home = tmp_path / "home"
    source = tmp_path / "chezmoi" / "home"

    plan = _build_chezmoi_completion_plan(
        source_root=source,
        home=home,
    )

    source_paths = {file.source.relative_to(source).as_posix() for file in plan.files}
    assert source_paths == {
        "dot_config/fish/completions/sase.fish",
        "dot_local/share/bash-completion/completions/sase",
        "dot_zfunc/_sase",
    }
    text_by_shell = {file.shell: file.text for file in plan.files}
    assert text_by_shell == {
        shell: emit_loader(shell, owner="chezmoi") for shell in ("bash", "fish", "zsh")
    }

    remove_paths = {path.relative_to(source).as_posix() for path in plan.remove_sources}
    assert remove_paths == {
        "dot_sase/completion/stamp/bash.json",
        "dot_sase/completion/stamp/fish.json",
        "dot_sase/completion/stamp/zsh.json",
    }


def test_build_plan_stamp_removals_are_home_independent(tmp_path: Path) -> None:
    mac_home = tmp_path / "Users" / "bryan"
    source = tmp_path / "chezmoi" / "home"

    plan = _build_chezmoi_completion_plan(
        source_root=source,
        home=mac_home,
    )

    assert {path.relative_to(source).as_posix() for path in plan.remove_sources} == {
        "dot_sase/completion/stamp/bash.json",
        "dot_sase/completion/stamp/fish.json",
        "dot_sase/completion/stamp/zsh.json",
    }
    assert all(str(mac_home) not in str(path) for path in plan.remove_sources)


def test_deploy_dry_run_is_read_only(tmp_path: Path) -> None:
    source = tmp_path / "chezmoi" / "home"

    result = deploy_chezmoi_completion(dry_run=True, source_root=source)

    assert result.exit_code == 0
    assert result.written_paths == ()
    assert result.removed_paths == ()
    assert not source.exists()


def test_deploy_writes_loaders_removes_legacy_stamps_and_delegates_chezmoi(
    tmp_path: Path,
) -> None:
    home = tmp_path / "home"
    source = tmp_path / "chezmoi" / "home"
    calls: list[tuple[tuple[Path, ...], object]] = []
    for shell in ("bash", "fish", "zsh"):
        stamp = source / "dot_sase" / "completion" / "stamp" / f"{shell}.json"
        stamp.parent.mkdir(parents=True, exist_ok=True)
        stamp.write_text("{}\n", encoding="utf-8")

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
    assert result.written_paths == result.plan.write_paths
    assert result.removed_paths == result.plan.remove_sources
    for path in result.plan.write_paths:
        assert path.is_file()
    for path in result.plan.remove_sources:
        assert not path.exists()
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
