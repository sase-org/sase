"""The shared torn-line-tolerant JSONL reader used by stall-log tests."""

from __future__ import annotations

from pathlib import Path

from tests._jsonl_rows import read_jsonl_rows


def test_missing_file_reads_as_empty(tmp_path: Path) -> None:
    assert read_jsonl_rows(tmp_path / "absent.jsonl") == ([], 0)


def test_torn_and_non_object_lines_are_skipped_and_counted(tmp_path: Path) -> None:
    path = tmp_path / "tui_stalls.jsonl"
    path.write_bytes(
        b'{"event": "tui_hitch"}\n\n"just a string"\n{"event": "tui_st\xe2\x80'
    )

    rows, skipped = read_jsonl_rows(path)

    assert rows == [{"event": "tui_hitch"}]
    assert skipped == 2
