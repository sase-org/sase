"""Offset-based incremental reads over one proc's combined log."""

from __future__ import annotations

from pathlib import Path

from sase.procs.logs import ProcLogCursor


def test_cursor_returns_only_new_bytes(tmp_path: Path) -> None:
    log = tmp_path / "abc.log"
    log.write_text("one\n", encoding="utf-8")
    cursor = ProcLogCursor("abc", log_path=log)

    assert cursor.read_new().text == "one\n"

    log.write_text("one\ntwo\n", encoding="utf-8")
    second = cursor.read_new()
    assert second.text == "two\n"
    assert second.lost_bytes == 0

    assert cursor.read_new().text == ""


def test_cursor_seek_end_skips_history(tmp_path: Path) -> None:
    log = tmp_path / "abc.log"
    log.write_text("old\n", encoding="utf-8")
    cursor = ProcLogCursor("abc", log_path=log)
    cursor.seek_end()

    assert cursor.read_new().text == ""

    log.write_text("old\nnew\n", encoding="utf-8")
    assert cursor.read_new().text == "new\n"


def test_cursor_recovers_rotated_sibling(tmp_path: Path) -> None:
    log = tmp_path / "abc.log"
    rotated = tmp_path / "abc.log.1"
    log.write_text("one\ntwo\n", encoding="utf-8")
    cursor = ProcLogCursor("abc", log_path=log)
    assert cursor.read_new().text == "one\ntwo\n"

    rotated.write_bytes(log.read_bytes())
    log.write_text("three\n", encoding="utf-8")
    recovered = cursor.read_new()
    assert recovered.text == "three\n"
    assert recovered.lost_bytes == 0

    log.write_text("three\nfour\n", encoding="utf-8")
    assert cursor.read_new().text == "four\n"


def test_cursor_drains_rotated_sibling_after_inode_change(tmp_path: Path) -> None:
    log = tmp_path / "abc.log"
    log.write_text("one\ntwo\n", encoding="utf-8")
    cursor = ProcLogCursor("abc", log_path=log, max_bytes_per_read=4)
    assert cursor.read_new().text == "one\n"

    log.rename(tmp_path / "abc.log.1")
    log.write_text("three\n", encoding="utf-8")
    # The per-read cap applies to the whole read: the sibling drain fills it.
    recovered = cursor.read_new()
    assert recovered.text == "two\n"
    assert recovered.lost_bytes == 0
    assert cursor.read_new().text == "thre"
    assert cursor.read_new().text == "e\n"


def test_cursor_reports_lost_bytes_when_rotated_sibling_is_short(
    tmp_path: Path,
) -> None:
    log = tmp_path / "abc.log"
    log.write_text("one\ntwo\nthree\n", encoding="utf-8")
    cursor = ProcLogCursor("abc", log_path=log)
    cursor.read_new()

    # Rotation drops the middle of the stream: the sibling only kept "one\n".
    (tmp_path / "abc.log.1").write_text("one\n", encoding="utf-8")
    log.write_text("four\n", encoding="utf-8")

    recovered = cursor.read_new()
    assert recovered.text == "four\n"
    assert recovered.lost_bytes == len("one\ntwo\nthree\n") - len("one\n")


def test_cursor_treats_truncation_as_loss(tmp_path: Path) -> None:
    log = tmp_path / "abc.log"
    log.write_text("one\ntwo\n", encoding="utf-8")
    cursor = ProcLogCursor("abc", log_path=log)
    cursor.read_new()

    log.write_text("fresh\n", encoding="utf-8")
    truncated = cursor.read_new()
    assert truncated.text == "fresh\n"
    assert truncated.lost_bytes == len("one\ntwo\n")


def test_cursor_tolerates_missing_files(tmp_path: Path) -> None:
    cursor = ProcLogCursor("abc", log_path=tmp_path / "abc.log")
    assert cursor.read_new().text == ""

    cursor.seek_end()
    assert cursor.read_new().text == ""


def test_cursor_caps_each_read(tmp_path: Path) -> None:
    log = tmp_path / "abc.log"
    log.write_text("a" * 100, encoding="utf-8")
    cursor = ProcLogCursor("abc", log_path=log, max_bytes_per_read=10)

    assert cursor.read_new().text == "a" * 10
    assert cursor.read_new().text == "a" * 10
