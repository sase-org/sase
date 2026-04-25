"""Tests for the 'sase file' handler (file list)."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pytest

from sase.main.file_handler import handle_file_command


def _ns(**kw: object) -> argparse.Namespace:
    return argparse.Namespace(**kw)


class TestFileList:
    def test_lists_files_in_directory(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        (tmp_path / "alpha.txt").write_text("a", encoding="utf-8")
        (tmp_path / "beta.txt").write_text("b", encoding="utf-8")
        (tmp_path / "subdir").mkdir()

        with pytest.raises(SystemExit) as exc:
            handle_file_command(
                _ns(file_subcommand="list", path=str(tmp_path), token="")
            )
        assert exc.value.code == 0

        candidates = json.loads(capsys.readouterr().out)
        names = {c["name"] for c in candidates}
        assert names == {"alpha.txt", "beta.txt", "subdir"}

        by_name = {c["name"]: c for c in candidates}
        assert by_name["subdir"]["is_dir"] is True
        assert by_name["subdir"]["display"] == "subdir/"
        assert by_name["alpha.txt"]["is_dir"] is False

    def test_token_filters_by_prefix(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        (tmp_path / "alpha.txt").write_text("a", encoding="utf-8")
        (tmp_path / "beta.txt").write_text("b", encoding="utf-8")

        with pytest.raises(SystemExit) as exc:
            handle_file_command(
                _ns(file_subcommand="list", path=str(tmp_path), token="al")
            )
        assert exc.value.code == 0
        names = {c["name"] for c in json.loads(capsys.readouterr().out)}
        assert names == {"alpha.txt"}

    def test_unknown_subcommand_exits_nonzero(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        with pytest.raises(SystemExit) as exc:
            handle_file_command(_ns(file_subcommand=None))
        assert exc.value.code == 1
        assert "Usage: sase file" in capsys.readouterr().out
