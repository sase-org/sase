"""Bead doctor CLI parsing coverage.

Split from ``tests.test_bead.test_cli_doctor``; the original module
re-exports these tests so its import path keeps working.
"""

from __future__ import annotations

import pytest

from sase.main.parser import create_parser


def test_doctor_parser_accepts_fix_aliases_and_documents_help(
    capsys: pytest.CaptureFixture[str],
) -> None:
    parser = create_parser()
    for flag in ("-F", "--fix-design-refs"):
        args = parser.parse_args(["bead", "doctor", flag])
        assert args.fix_design_refs is True

    with pytest.raises(SystemExit) as excinfo:
        parser.parse_args(["bead", "doctor", "-h"])
    assert excinfo.value.code == 0
    assert "--fix-design-refs" in capsys.readouterr().out


def test_doctor_parser_accepts_projection_repair_and_yes_aliases(
    capsys: pytest.CaptureFixture[str],
) -> None:
    parser = create_parser()
    for flag in ("-P", "--fix-projection"):
        args = parser.parse_args(["bead", "doctor", flag])
        assert args.fix_projection is True
    for flag in ("-y", "--yes"):
        args = parser.parse_args(["bead", "doctor", flag])
        assert args.yes is True

    with pytest.raises(SystemExit) as excinfo:
        parser.parse_args(["bead", "doctor", "-h"])
    assert excinfo.value.code == 0
    help_text = capsys.readouterr().out
    assert "--fix-projection" in help_text
    assert "--yes" in help_text


def test_doctor_parser_accepts_fix_issue_prefix_alias_and_documents_help(
    capsys: pytest.CaptureFixture[str],
) -> None:
    parser = create_parser()
    for flag in ("-I", "--fix-issue-prefix"):
        args = parser.parse_args(["bead", "doctor", flag])
        assert args.fix_issue_prefix is True

    with pytest.raises(SystemExit) as excinfo:
        parser.parse_args(["bead", "doctor", "-h"])
    assert excinfo.value.code == 0
    assert "--fix-issue-prefix" in capsys.readouterr().out


def test_doctor_parser_accepts_fix_plan_archive_alias_and_documents_help(
    capsys: pytest.CaptureFixture[str],
) -> None:
    parser = create_parser()
    for flag in ("-A", "--fix-plan-archive"):
        args = parser.parse_args(["bead", "doctor", flag])
        assert args.fix_plan_archive is True

    with pytest.raises(SystemExit) as excinfo:
        parser.parse_args(["bead", "doctor", "-h"])
    assert excinfo.value.code == 0
    assert "--fix-plan-archive" in capsys.readouterr().out


def test_doctor_parser_accepts_verify_cache_alias_and_documents_help(
    capsys: pytest.CaptureFixture[str],
) -> None:
    parser = create_parser()
    for flag in ("-C", "--verify-cache"):
        args = parser.parse_args(["bead", "doctor", flag])
        assert args.verify_cache is True

    with pytest.raises(SystemExit) as excinfo:
        parser.parse_args(["bead", "doctor", "-h"])
    assert excinfo.value.code == 0
    assert "--verify-cache" in capsys.readouterr().out
