"""Tests for lazy top-level command parser construction."""

from __future__ import annotations

import argparse
import subprocess
import sys

import pytest

from sase.main.parser import (
    _COMMAND_REGISTRARS,
    create_parser,
    parser_only_hint,
)


def _root_commands(parser: argparse.ArgumentParser) -> set[str]:
    action = next(
        action
        for action in parser._actions
        if isinstance(action, argparse._SubParsersAction)
    )
    return set(action.choices)


def test_full_parser_commands_match_lazy_registry() -> None:
    """The full and narrow parser paths share one command inventory."""
    assert _root_commands(create_parser()) == set(_COMMAND_REGISTRARS)


def test_construction_still_rejects_badly_formed_help() -> None:
    """Shared validation formatters must still catch broken help templates."""
    parser = create_parser(only="version")
    with pytest.raises(ValueError, match="badly formed help string"):
        parser.add_argument("--x", help="%(unknown)s")


def test_parser_for_builds_only_the_requested_command_tree() -> None:
    """Help helpers must not pay for the full command inventory."""
    from tests.main.parser_help_helpers import parser_for

    parser = parser_for(("sase", "bead"))
    args = parser.parse_args(["show", "sase-1"])

    assert args.bead_subcommand == "show"
    assert args.id == "sase-1"


def test_narrow_parser_registers_only_requested_command() -> None:
    """A narrow parser does not build unrelated top-level command trees."""
    parser = create_parser(only="bead")

    assert _root_commands(parser) == {"bead"}
    args = parser.parse_args(["bead", "show", "sase-1"])
    assert args.command == "bead"
    assert args.bead_subcommand == "show"


def test_narrow_parser_supports_compatibility_alias() -> None:
    """Selecting an alias loads its one shared registrar."""
    parser = create_parser(only="artifact-file")

    assert _root_commands(parser) == {"artifact", "artifact-file"}
    args = parser.parse_args(["artifact-file", "create", "--path", "out.txt"])
    assert args.command == "artifact-file"


@pytest.mark.parametrize("command", ["patch", "changespec"])
def test_patch_parser_supports_canonical_command_and_legacy_alias(
    command: str,
) -> None:
    parser = create_parser(only=command)

    assert _root_commands(parser) == {"patch", "changespec"}  # legacy command alias
    args = parser.parse_args([command, "sync-deltas", "--patch", "feature"])
    assert args.command == command
    assert args.patch_subcommand == "sync-deltas"
    assert args.changespec_subcommand == "sync-deltas"
    assert args.patch == "feature"
    assert args.cl_name == "feature"


@pytest.mark.parametrize("command", ["stitch", "vcs"])
def test_stitch_parser_supports_canonical_command_and_legacy_alias(
    command: str,
) -> None:
    parser = create_parser(only=command)

    assert _root_commands(parser) == {"stitch", "vcs"}  # legacy command alias
    args = parser.parse_args([command, "list"])
    assert args.command == command
    assert args.stitch_subcommand == "list"


@pytest.mark.parametrize(
    ("argv", "expected"),
    [
        (["sase", "bead"], "bead"),
        (["sase", "patch"], "patch"),
        (["sase", "stitch"], "stitch"),
        (["sase", "vcs"], "vcs"),
        (["sase"], None),
        (["sase", "--help"], None),
        (["sase", "-H"], None),
        (["sase", "bogus"], None),
    ],
)
def test_parser_only_hint_uses_narrow_path_only_when_safe(
    argv: list[str],
    expected: str | None,
) -> None:
    """Root help and error paths retain the complete command inventory."""
    assert parser_only_hint(argv) == expected


@pytest.mark.parametrize("argv", [[], ["--help"], ["-H"], ["bogus"]])
def test_full_parser_fallback_output_is_unchanged(
    argv: list[str],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Fallback entry paths exactly match direct full-parser behavior."""
    with pytest.raises(SystemExit) as expected_exit:
        create_parser().parse_args(argv)
    expected_output = capsys.readouterr()

    from sase.main import entry

    monkeypatch.setattr(sys, "argv", ["sase", *argv])
    with pytest.raises(SystemExit) as actual_exit:
        entry.main()
    actual_output = capsys.readouterr()

    assert actual_exit.value.code == expected_exit.value.code
    assert actual_output == expected_output


def test_bead_show_parser_does_not_import_unrelated_registrars() -> None:
    """The real entry path keeps heavy unrelated parser modules unloaded."""
    script = """
import sys

from sase.main.entry import main

sys.argv = ["sase", "bead", "show", "--help"]
try:
    main()
except SystemExit as exc:
    assert exc.code == 0
else:
    raise AssertionError("entry point returned without exiting")

assert "sase.main.parser_ace" not in sys.modules
assert "sase.main.parser_full_registrars" not in sys.modules
assert "sase.main.parser_stitch" not in sys.modules
assert "sase.main.parser_vcs" not in sys.modules
"""
    result = subprocess.run(
        [sys.executable, "-c", script],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr


def test_artifact_parser_uses_lightweight_file_types_module() -> None:
    """Argparse choices do not import the heavy artifact facade."""
    script = """
import sys

import sase.main.parser_artifact

assert "sase.core.artifact_file_facade" not in sys.modules
"""
    result = subprocess.run(
        [sys.executable, "-c", script],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr


def test_stitch_parser_uses_lightweight_commit_methods_module() -> None:
    """`sase stitch create` argparse choices do not import the commit workflow."""
    script = """
import sys

import sase.main.parser_stitch

assert "sase.workflows.commit" not in sys.modules
"""
    result = subprocess.run(
        [sys.executable, "-c", script],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr


def test_commit_methods_leaf_module_matches_workflow_types_reexport() -> None:
    """The workflow types module re-exports the same leaf-module objects."""
    from sase import commit_methods
    from sase.workflows.commit import workflow_types

    assert workflow_types.VALID_METHODS is commit_methods.VALID_METHODS
    assert workflow_types.METHOD_ALIASES is commit_methods.METHOD_ALIASES
