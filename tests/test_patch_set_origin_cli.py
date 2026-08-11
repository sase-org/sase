"""CLI coverage for ``sase patch set-origin``."""

from __future__ import annotations

from pathlib import Path

import pytest

from sase.main.parser import create_parser
from sase.main.patch_handler import _handle_set_origin


def _project_file(tmp_path: Path, name: str = "sase_feature") -> Path:
    project = tmp_path / "sase.sase"
    project.write_text(
        f"NAME: {name}\n"
        "DESCRIPTION:\n"
        "  Example\n"
        "PR: https://example.test/pull/1\n"
        "STATUS: Draft\n",
        encoding="utf-8",
    )
    return project


def test_set_origin_parser_requires_name_and_valid_choice() -> None:
    parser = create_parser()
    args = parser.parse_args(["patch", "set-origin", "sase_feature", "external"])

    assert args.patch_subcommand == "set-origin"
    assert args.name == "sase_feature"
    assert args.origin == "external"

    with pytest.raises(SystemExit):
        parser.parse_args(["patch", "set-origin", "sase_feature", "bogus"])


def test_handle_set_origin_writes_normalized_field(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    project = _project_file(tmp_path)
    parser = create_parser()
    args = parser.parse_args(
        [
            "patch",
            "set-origin",
            "sase_feature",
            "external",
            "-p",
            str(project),
        ]
    )

    exit_code = _handle_set_origin(args)

    assert exit_code == 0
    assert "PR_ORIGIN: external" in project.read_text(encoding="utf-8")
    out = capsys.readouterr().out
    assert "PR_ORIGIN set to external" in out


def test_handle_set_origin_reports_missing_patch(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    project = _project_file(tmp_path)
    parser = create_parser()
    args = parser.parse_args(
        [
            "patch",
            "set-origin",
            "does_not_exist",
            "external",
            "-p",
            str(project),
        ]
    )

    exit_code = _handle_set_origin(args)

    assert exit_code == 1
    err = capsys.readouterr().err
    assert "Patch not found: does_not_exist" in err


def test_handle_set_origin_reports_missing_project_file(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    parser = create_parser()
    args = parser.parse_args(
        [
            "patch",
            "set-origin",
            "sase_feature",
            "external",
            "-p",
            str(tmp_path / "does_not_exist.sase"),
        ]
    )

    exit_code = _handle_set_origin(args)

    assert exit_code == 1
    err = capsys.readouterr().err
    assert "project file not found" in err
