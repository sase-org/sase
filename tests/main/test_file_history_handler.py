"""Tests for the 'sase file-history' handler (list / delete)."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from unittest.mock import patch

import pytest

from sase.main.file_history_handler import handle_file_history_command


def _ns(**kw: object) -> argparse.Namespace:
    return argparse.Namespace(**kw)


class TestFileHistoryList:
    def test_empty_history_emits_empty_array(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        with patch(
            "sase.history.file_references._HISTORY_FILE", tmp_path / "missing.json"
        ):
            with pytest.raises(SystemExit) as exc:
                handle_file_history_command(_ns(file_history_subcommand="list"))
        assert exc.value.code == 0
        assert json.loads(capsys.readouterr().out) == []

    def test_populated_history_round_trips(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        from sase.history.file_references import record_file_references

        store = tmp_path / "hist.json"
        with patch("sase.history.file_references._HISTORY_FILE", store):
            record_file_references(["/etc/hosts", "~/notes.md"])
            with pytest.raises(SystemExit) as exc:
                handle_file_history_command(_ns(file_history_subcommand="list"))
        assert exc.value.code == 0
        # Most-recent-first ordering is preserved.
        assert json.loads(capsys.readouterr().out) == ["~/notes.md", "/etc/hosts"]


class TestFileHistoryDelete:
    def test_delete_existing_removes_entry(self, tmp_path: Path) -> None:
        from sase.history.file_references import (
            load_file_references,
            record_file_references,
        )

        store = tmp_path / "hist.json"
        with patch("sase.history.file_references._HISTORY_FILE", store):
            record_file_references(["/a", "/b", "/c"])
            with pytest.raises(SystemExit) as exc:
                handle_file_history_command(
                    _ns(file_history_subcommand="delete", path="/b")
                )
            assert exc.value.code == 0
            assert load_file_references() == ["/c", "/a"]

    def test_delete_nonexistent_is_silent_noop(self, tmp_path: Path) -> None:
        from sase.history.file_references import (
            load_file_references,
            record_file_references,
        )

        store = tmp_path / "hist.json"
        with patch("sase.history.file_references._HISTORY_FILE", store):
            record_file_references(["/a"])
            with pytest.raises(SystemExit) as exc:
                handle_file_history_command(
                    _ns(file_history_subcommand="delete", path="/missing")
                )
            assert exc.value.code == 0
            assert load_file_references() == ["/a"]

    def test_delete_against_missing_file_is_noop(self, tmp_path: Path) -> None:
        store = tmp_path / "missing.json"
        with patch("sase.history.file_references._HISTORY_FILE", store):
            with pytest.raises(SystemExit) as exc:
                handle_file_history_command(
                    _ns(file_history_subcommand="delete", path="/anything")
                )
            assert exc.value.code == 0
            assert not store.exists()


class TestFileHistoryUnknownSubcommand:
    def test_unknown_subcommand_exits_nonzero(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        with pytest.raises(SystemExit) as exc:
            handle_file_history_command(_ns(file_history_subcommand=None))
        assert exc.value.code == 1
        assert "Usage: sase file-history" in capsys.readouterr().out
