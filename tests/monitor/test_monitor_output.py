"""Tests for :mod:`sase.monitor.output`."""

from __future__ import annotations

from pathlib import Path

from sase.monitor.output import OutputCapture


def test_output_capture_retains_everything_under_the_cap(tmp_path: Path) -> None:
    del tmp_path
    capture = OutputCapture(max_bytes=1024)
    capture.append_bytes(b"line one\n")
    capture.append_bytes(b"line two\n")

    assert not capture.truncated
    assert capture.retained_text() == "line one\nline two\n"
    assert capture.total_bytes == len("line one\nline two\n")


def test_output_capture_elides_the_middle_once_over_the_cap(tmp_path: Path) -> None:
    del tmp_path
    capture = OutputCapture(max_bytes=100)
    for i in range(200):
        capture.append_bytes(f"line {i:04d}\n".encode())

    assert capture.truncated
    retained = capture.retained_text()
    assert "bytes elided" in retained
    assert retained.startswith("line 0000")
    assert retained.rstrip().endswith("line 0199")


def test_output_capture_never_exceeds_the_cap_plus_marker(tmp_path: Path) -> None:
    del tmp_path
    max_bytes = 200
    capture = OutputCapture(max_bytes=max_bytes)
    for i in range(500):
        capture.append_bytes(f"a very chatty line {i:05d}\n".encode())

    retained = capture.retained_text()
    marker_start = retained.index("\n… ")
    marker_end = retained.index(" …\n", marker_start) + len(" …\n")
    head = retained[:marker_start]
    tail = retained[marker_end:]
    assert len(head.encode("utf-8")) <= max_bytes // 2
    assert len(tail.encode("utf-8")) <= max_bytes // 2


def test_output_capture_replaces_invalid_utf8() -> None:
    capture = OutputCapture(max_bytes=1024)
    capture.append_bytes(b"ok \xff done\n")

    assert capture.retained_text() == "ok \ufffd done\n"
