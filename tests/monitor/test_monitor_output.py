"""Tests for :mod:`sase.monitor.output`."""

from __future__ import annotations

from pathlib import Path

from sase.monitor.output import OutputCapture


def test_output_capture_retains_everything_under_the_cap(tmp_path: Path) -> None:
    log_path = tmp_path / "live_reply.md"
    capture = OutputCapture(str(log_path), max_bytes=1024)
    capture.append("line one\n")
    capture.append("line two\n")
    capture.close()

    assert not capture.truncated
    assert capture.retained_text() == "line one\nline two\n"
    assert log_path.read_text(encoding="utf-8") == "line one\nline two\n"
    assert capture.total_bytes == len("line one\nline two\n")


def test_output_capture_elides_the_middle_once_over_the_cap(tmp_path: Path) -> None:
    log_path = tmp_path / "live_reply.md"
    capture = OutputCapture(str(log_path), max_bytes=100)
    for i in range(200):
        capture.append(f"line {i:04d}\n")
    capture.close()

    assert capture.truncated
    retained = capture.retained_text()
    assert "bytes elided" in retained
    assert retained.startswith("line 0000")
    assert retained.rstrip().endswith("line 0199")
    # The full stream is never lost from disk, only from the retained view.
    on_disk = log_path.read_text(encoding="utf-8")
    assert "line 0000\n" in on_disk
    assert "line 0199\n" in on_disk
    assert len(on_disk) == capture.total_bytes


def test_output_capture_never_exceeds_the_cap_plus_marker(tmp_path: Path) -> None:
    log_path = tmp_path / "live_reply.md"
    max_bytes = 200
    capture = OutputCapture(str(log_path), max_bytes=max_bytes)
    for i in range(500):
        capture.append(f"a very chatty line {i:05d}\n")
    capture.close()

    retained = capture.retained_text()
    marker_start = retained.index("\n… ")
    marker_end = retained.index(" …\n", marker_start) + len(" …\n")
    head = retained[:marker_start]
    tail = retained[marker_end:]
    assert len(head.encode("utf-8")) <= max_bytes // 2
    assert len(tail.encode("utf-8")) <= max_bytes // 2
