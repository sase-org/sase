"""Tests for the Footprint status and clear CLI commands."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from sase.main.footprint_handler import _handle_clear, _handle_status
from sase.main.parser import create_parser


def test_status_json_is_the_ledger_wire(monkeypatch, capsys) -> None:
    wire = {
        "schema_version": 1,
        "generation": 0,
        "first_record_day": None,
        "spool_bytes_pending": 0,
        "coverage": [],
    }
    monkeypatch.setattr("sase.footprint.fold.fold_if_stale", lambda: wire)

    assert _handle_status(argparse.Namespace(format="json")) == 0
    assert json.loads(capsys.readouterr().out) == wire


def test_status_renders_rich_panel(monkeypatch, tmp_path: Path, capsys) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / "home"))
    monkeypatch.setattr(
        "sase.footprint.fold.fold_if_stale",
        lambda: {
            "schema_version": 1,
            "generation": 0,
            "first_record_day": "2026-10-20",
            "last_fold_at": "2026-10-27T00:00:00Z",
            "spool_files_pending": 0,
            "spool_bytes_pending": 0,
            "ledger_bytes": 1024,
            "catalog_rev": "rev123",
            "catalog_count": 7,
            "coverage": [],
            "torn_total": 0,
            "dropped_total": 0,
            "unknown_ids_total": 0,
        },
    )

    assert _handle_status(argparse.Namespace(format="rich")) == 0
    output = capsys.readouterr().out
    assert "Footprint status" in output
    assert "Coverage" in output
    assert "Faults" in output
    assert "feature IDs and counts only" in output


def test_clear_requires_confirmation_without_yes(monkeypatch, capsys) -> None:
    class NonInteractive:
        def isatty(self) -> bool:
            return False

    monkeypatch.setattr("sase.main.footprint_handler.sys.stdin", NonInteractive())
    monkeypatch.setattr(
        "sase.footprint.fold.clear_ledger",
        lambda: (_ for _ in ()).throw(AssertionError("clear must not run")),
    )

    assert _handle_clear(argparse.Namespace(yes=False)) == 2
    assert "Confirmation required" in capsys.readouterr().err


def test_clear_yes_runs_clear_and_reports_generation(monkeypatch, capsys) -> None:
    monkeypatch.setattr("sase.footprint.fold.clear_ledger", lambda: {"generation": 3})

    assert _handle_clear(argparse.Namespace(yes=True)) == 0
    assert "generation 3" in capsys.readouterr().out


def test_status_and_clear_options_are_registered() -> None:
    args = create_parser().parse_args(["footprint", "status", "-f", "json"])
    assert args.footprint_subcommand == "status"
    assert args.format == "json"
    clear = create_parser().parse_args(["footprint", "clear", "-y"])
    assert clear.footprint_subcommand == "clear"
    assert clear.yes is True
