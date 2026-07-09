"""Tests for ``sase sdd init`` handling."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from sase.main.sdd_handler import handle_sdd_command
from tests.main.sdd_handler_helpers import (
    directory_readmes,
    make_args,
    mark_tmp_path_as_project,
)

__all__ = ["mark_tmp_path_as_project"]

pytestmark = pytest.mark.usefixtures("mark_tmp_path_as_project")


def test_init_creates_readme_for_project_root(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    with pytest.raises(SystemExit) as excinfo:
        handle_sdd_command(make_args(sdd_subcommand="init", path=str(tmp_path)))

    assert excinfo.value.code == 0
    readme = tmp_path / "sdd" / "README.md"
    asset = tmp_path / "sdd" / "assets" / "sdd-directory-map.png"
    config = tmp_path / "sase.yml"
    assert config.read_text(encoding="utf-8") == "sdd:\n  version_controlled: true\n"
    assert readme.exists()
    assert asset.exists()
    readmes = directory_readmes(tmp_path / "sdd")
    assert all(path.exists() for path in readmes.values())
    assert str(readme) in capsys.readouterr().out
    text = readme.read_text(encoding="utf-8")
    assert "# Structured Development Docs" in text
    assert "![SDD directory map](assets/sdd-directory-map.png)" in text
    assert "`prompts/`" in text
    assert "`tales/`" in text
    assert "`myths/`" in text
    assert "`research/`" in text
    assert "`sase sdd path`" in text
    assert "`SASE_SDD_DIR`" in text
    assert "`research/202605/example.md`" in text
    assert "`sase sdd validate`" in text
    assert "# Tales" in readmes["tales"].read_text(encoding="utf-8")
    assert "task-level implementation plans" in readmes["tales"].read_text(
        encoding="utf-8"
    )
    assert "larger work plans" in readmes["epics"].read_text(encoding="utf-8")
    assert "broad roadmap or strategy" in readmes["legends"].read_text(encoding="utf-8")
    assert "long-horizon narrative" in readmes["myths"].read_text(encoding="utf-8")
    assert "exploratory findings" in readmes["research"].read_text(encoding="utf-8")


def test_init_appends_sdd_config_to_existing_sase_yml(tmp_path: Path) -> None:
    config = tmp_path / "sase.yml"
    config.write_text(
        "# local config\nworkspace:\n  root: xdg-state\n", encoding="utf-8"
    )

    with pytest.raises(SystemExit) as excinfo:
        handle_sdd_command(make_args(sdd_subcommand="init", path=str(tmp_path)))

    assert excinfo.value.code == 0
    assert config.read_text(encoding="utf-8") == (
        "# local config\n"
        "workspace:\n"
        "  root: xdg-state\n"
        "\n"
        "sdd:\n"
        "  version_controlled: true\n"
    )


def test_init_inserts_version_controlled_under_existing_sdd_config(
    tmp_path: Path,
) -> None:
    config = tmp_path / "sase.yml"
    config.write_text("sdd:\n  other: keep\n", encoding="utf-8")

    with pytest.raises(SystemExit) as excinfo:
        handle_sdd_command(make_args(sdd_subcommand="init", path=str(tmp_path)))

    assert excinfo.value.code == 0
    assert config.read_text(encoding="utf-8") == (
        "sdd:\n  version_controlled: true\n  other: keep\n"
    )


def test_init_inserts_version_controlled_under_empty_sdd_config(
    tmp_path: Path,
) -> None:
    config = tmp_path / "sase.yml"
    config.write_text("sdd:\n", encoding="utf-8")

    with pytest.raises(SystemExit) as excinfo:
        handle_sdd_command(make_args(sdd_subcommand="init", path=str(tmp_path)))

    assert excinfo.value.code == 0
    assert config.read_text(encoding="utf-8") == "sdd:\n  version_controlled: true\n"


def test_init_updates_false_version_controlled(tmp_path: Path) -> None:
    config = tmp_path / "sase.yml"
    config.write_text(
        "sdd:\n  version_controlled: false # opt in here\n",
        encoding="utf-8",
    )

    with pytest.raises(SystemExit) as excinfo:
        handle_sdd_command(make_args(sdd_subcommand="init", path=str(tmp_path)))

    assert excinfo.value.code == 0
    assert config.read_text(encoding="utf-8") == (
        "sdd:\n  version_controlled: true # opt in here\n"
    )


def test_init_path_in_dot_sase_sdd_updates_project_root_config(
    tmp_path: Path,
) -> None:
    sdd_root = tmp_path / ".sase" / "sdd"

    with pytest.raises(SystemExit) as excinfo:
        handle_sdd_command(make_args(sdd_subcommand="init", path=str(sdd_root)))

    assert excinfo.value.code == 0
    assert (tmp_path / "sase.yml").read_text(encoding="utf-8") == (
        "sdd:\n  version_controlled: true\n"
    )
    assert (sdd_root / "README.md").exists()


def test_init_storage_local_writes_enum_and_initializes_local_store(
    tmp_path: Path,
) -> None:
    with pytest.raises(SystemExit) as excinfo:
        handle_sdd_command(
            make_args(sdd_subcommand="init", path=str(tmp_path), storage="local")
        )

    assert excinfo.value.code == 0
    assert (tmp_path / "sase.yml").read_text(encoding="utf-8") == (
        "sdd:\n  storage: local\n"
    )
    assert (tmp_path / ".sase" / "sdd" / "README.md").exists()
    assert not (tmp_path / "sdd" / "README.md").exists()


def test_init_storage_removes_deprecated_alias(tmp_path: Path) -> None:
    (tmp_path / "sase.yml").write_text(
        "sdd:\n  version_controlled: true\n  repo:\n    name: custom-sdd\n",
        encoding="utf-8",
    )

    with pytest.raises(SystemExit) as excinfo:
        handle_sdd_command(
            make_args(sdd_subcommand="init", path=str(tmp_path), storage="local")
        )

    assert excinfo.value.code == 0
    assert (tmp_path / "sase.yml").read_text(encoding="utf-8") == (
        "sdd:\n  repo:\n    name: custom-sdd\n  storage: local\n"
    )


def test_init_check_reports_missing_sdd_without_writing(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    with pytest.raises(SystemExit) as excinfo:
        handle_sdd_command(
            make_args(sdd_subcommand="init", path=str(tmp_path), check=True)
        )

    assert excinfo.value.code == 1
    assert not (tmp_path / "sdd").exists()
    assert not (tmp_path / "sase.yml").exists()
    out = capsys.readouterr().out
    assert "SASE initialization check" in out
    assert "Needs attention:" in out
    assert "init sdd" in out
    assert "write legacy SDD init config" in out
    assert "create SDD README files and directory map" in out


def test_init_check_current_sdd_exits_zero(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from sase.sdd.files import write_sdd_readme

    write_sdd_readme(str(tmp_path))
    (tmp_path / "sase.yml").write_text(
        "sdd:\n  version_controlled: true\n",
        encoding="utf-8",
    )

    with pytest.raises(SystemExit) as excinfo:
        handle_sdd_command(
            make_args(sdd_subcommand="init", path=str(tmp_path), check=True)
        )

    assert excinfo.value.code == 0
    out = capsys.readouterr().out
    assert "SASE is initialized. No init subcommands need to run." in out
    assert "Checked: sdd." in out


def test_init_check_current_separate_repo_sdd_exits_zero(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from sase.sdd.files import write_sdd_readme
    from sase.sdd.store import _write_sdd_store_record

    write_sdd_readme(str(tmp_path / ".sase" / "sdd"))
    (tmp_path / "sase.yml").write_text(
        "sdd:\n  storage: separate_repo\n",
        encoding="utf-8",
    )
    _write_sdd_store_record(
        tmp_path,
        {
            "storage": "separate_repo",
            "provider": "github",
            "repo": "acme/widget--sdd",
            "remote_url": "git@github.com:acme/widget--sdd.git",
            "discovery": "found",
        },
    )

    with pytest.raises(SystemExit) as excinfo:
        handle_sdd_command(
            make_args(sdd_subcommand="init", path=str(tmp_path), check=True)
        )

    assert excinfo.value.code == 0
    assert not (tmp_path / "sdd").exists()
    out = capsys.readouterr().out
    assert "SASE is initialized. No init subcommands need to run." in out
    assert "Checked: sdd." in out


def test_init_check_reports_missing_config_without_writing(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from sase.sdd.files import write_sdd_readme

    write_sdd_readme(str(tmp_path))

    with pytest.raises(SystemExit) as excinfo:
        handle_sdd_command(
            make_args(sdd_subcommand="init", path=str(tmp_path), check=True)
        )

    assert excinfo.value.code == 1
    assert not (tmp_path / "sase.yml").exists()
    out = capsys.readouterr().out
    assert "write legacy SDD init config" in out


def test_init_invalid_sase_yml_exits_without_writing_sdd(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    config = tmp_path / "sase.yml"
    config.write_text("invalid: yaml: [not closed\n", encoding="utf-8")

    with pytest.raises(SystemExit) as excinfo:
        handle_sdd_command(make_args(sdd_subcommand="init", path=str(tmp_path)))

    assert excinfo.value.code == 1
    assert config.read_text(encoding="utf-8") == "invalid: yaml: [not closed\n"
    assert not (tmp_path / "sdd").exists()
    err = capsys.readouterr().err
    assert "invalid YAML" in err


def test_init_check_invalid_sase_yml_reports_blocker_without_writing_sdd(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    config = tmp_path / "sase.yml"
    config.write_text("invalid: yaml: [not closed\n", encoding="utf-8")

    with pytest.raises(SystemExit) as excinfo:
        handle_sdd_command(
            make_args(sdd_subcommand="init", path=str(tmp_path), check=True)
        )

    assert excinfo.value.code == 1
    assert config.read_text(encoding="utf-8") == "invalid: yaml: [not closed\n"
    assert not (tmp_path / "sdd").exists()
    out = capsys.readouterr().out
    assert "Blockers:" in out
    assert "invalid YAML" in out


def test_init_non_mapping_sdd_config_exits_without_overwriting(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    config = tmp_path / "sase.yml"
    config.write_text("sdd: false\n", encoding="utf-8")

    with pytest.raises(SystemExit) as excinfo:
        handle_sdd_command(make_args(sdd_subcommand="init", path=str(tmp_path)))

    assert excinfo.value.code == 1
    assert config.read_text(encoding="utf-8") == "sdd: false\n"
    assert not (tmp_path / "sdd").exists()
    err = capsys.readouterr().err
    assert "non-mapping sdd config" in err


def test_init_null_sdd_config_exits_without_overwriting(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    config = tmp_path / "sase.yml"
    config.write_text("sdd: null\n", encoding="utf-8")

    with pytest.raises(SystemExit) as excinfo:
        handle_sdd_command(make_args(sdd_subcommand="init", path=str(tmp_path)))

    assert excinfo.value.code == 1
    assert config.read_text(encoding="utf-8") == "sdd: null\n"
    assert not (tmp_path / "sdd").exists()
    err = capsys.readouterr().err
    assert "non-mapping sdd config" in err


def test_init_sdd_alias_dispatches_to_sdd_init(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from sase.main.entry import main

    calls: list[str | None] = []
    readme_path = tmp_path / "sdd" / "README.md"

    def fake_write_sdd_readme(path: str | None = None, **_: object) -> Path:
        calls.append(path)
        return readme_path

    monkeypatch.setattr(sys, "argv", ["sase", "init", "sdd", "-p", str(tmp_path)])
    monkeypatch.setattr("sase.sdd.files.write_sdd_readme", fake_write_sdd_readme)

    with pytest.raises(SystemExit) as excinfo:
        main()

    assert excinfo.value.code == 0
    assert calls == [str(tmp_path)]
    assert (tmp_path / "sase.yml").read_text(encoding="utf-8") == (
        "sdd:\n  version_controlled: true\n"
    )
    assert str(readme_path) in capsys.readouterr().out


def test_init_overwrites_stale_readme_and_asset_idempotently(tmp_path: Path) -> None:
    readme = tmp_path / "sdd" / "README.md"
    asset = tmp_path / "sdd" / "assets" / "sdd-directory-map.png"
    readme.parent.mkdir(parents=True)
    readme.write_text("stale\n", encoding="utf-8")
    asset.parent.mkdir(parents=True)
    asset.write_bytes(b"stale\n")
    readmes = directory_readmes(tmp_path / "sdd")
    for directory_readme in readmes.values():
        directory_readme.parent.mkdir(parents=True, exist_ok=True)
        directory_readme.write_text("stale\n", encoding="utf-8")
    (tmp_path / "sase.yml").write_text(
        "sdd:\n  version_controlled: true\n",
        encoding="utf-8",
    )

    with pytest.raises(SystemExit) as first:
        handle_sdd_command(make_args(sdd_subcommand="init", path=str(tmp_path)))
    first_content = readme.read_text(encoding="utf-8")
    first_asset_content = asset.read_bytes()
    first_readme_contents = {
        kind: path.read_text(encoding="utf-8") for kind, path in readmes.items()
    }

    with pytest.raises(SystemExit) as second:
        handle_sdd_command(make_args(sdd_subcommand="init", path=str(tmp_path)))

    assert first.value.code == 0
    assert second.value.code == 0
    assert first_content != "stale\n"
    assert first_asset_content != b"stale\n"
    assert all(content != "stale\n" for content in first_readme_contents.values())
    assert readme.read_text(encoding="utf-8") == first_content
    assert asset.read_bytes() == first_asset_content
    assert {
        kind: path.read_text(encoding="utf-8") for kind, path in readmes.items()
    } == first_readme_contents
