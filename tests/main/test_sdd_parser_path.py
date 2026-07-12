"""Tests for ``sase sdd`` parser registration and path handling."""

from __future__ import annotations

from pathlib import Path

import pytest

from sase.main.parser import create_parser
from sase.main.sdd_handler import handle_sdd_command
from tests.main.sdd_handler_helpers import make_args, mark_tmp_path_as_project

__all__ = ["mark_tmp_path_as_project"]

pytestmark = pytest.mark.usefixtures("mark_tmp_path_as_project")


def test_parser_registers_sdd_subcommands() -> None:
    parser = create_parser()

    args = parser.parse_args(["sdd", "init", "-p", "sdd"])
    assert args.command == "sdd"
    assert args.sdd_subcommand == "init"
    assert args.path == "sdd"
    assert args.check is False

    args = parser.parse_args(["sdd", "init", "--check"])
    assert args.sdd_subcommand == "init"
    assert args.check is True

    args = parser.parse_args(
        ["sdd", "validate", "-p", "sdd", "-j", "-q", "--strict", "-W"]
    )
    assert args.command == "sdd"
    assert args.sdd_subcommand == "validate"
    assert args.path == "sdd"
    assert args.json is True
    assert args.quiet is True
    assert args.strict is True
    assert args.show_warnings is True

    args = parser.parse_args(["sdd", "list", "-p", "sdd", "-k", "prompts", "-j"])
    assert args.sdd_subcommand == "list"
    assert args.kind == "prompts"

    args = parser.parse_args(["sdd", "list", "-p", "sdd", "-k", "tales"])
    assert args.kind == "tales"

    args = parser.parse_args(["sdd", "path", "research"])
    assert args.sdd_subcommand == "path"
    assert args.kind == "research"

    args = parser.parse_args(["sdd", "path", "--ensure", "research"])
    assert args.ensure is True

    args = parser.parse_args(["sdd", "repair-links", "-p", "sdd", "-w"])
    assert args.write is True

    with pytest.raises(SystemExit):
        parser.parse_args(["sdd", "init", "--storage", "local"])
    with pytest.raises(SystemExit):
        parser.parse_args(["sdd", "migrate"])


@pytest.mark.parametrize(
    ("provider", "kind", "expected_relpath"),
    [
        ("bare_git", None, "sdd"),
        (None, "research", ".sase/sdd/research"),
        ("github", "beads", ".sase/sdd/beads"),
    ],
)
def test_path_prints_effective_sdd_directory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    provider: str | None,
    kind: str | None,
    expected_relpath: str,
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("sase.vcs_provider.detect_vcs", lambda _cwd: provider)
    monkeypatch.setattr(
        "sase.workspace_provider.get_sdd_storage_policy_by_vcs",
        lambda name: {
            "bare_git": "in_tree",
            "github": "separate_repo",
        }.get(name),
    )
    args = make_args(sdd_subcommand="path", kind=kind)

    with pytest.raises(SystemExit) as excinfo:
        handle_sdd_command(args)

    assert excinfo.value.code == 0
    assert capsys.readouterr().out.strip() == str(tmp_path / expected_relpath)
