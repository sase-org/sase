"""Regression tests for the shared pipe-backed bounded log writer."""

from __future__ import annotations

import pytest

from sase.logs.pipe import BoundedLogPipe


def test_bounded_log_pipe_reports_chunk_callback_errors_after_disk_append(
    tmp_path,
) -> None:
    path = tmp_path / "stream.log"

    def fail_on_chunk(_chunk: bytes) -> None:
        raise RuntimeError("capture failed")

    pipe = BoundedLogPipe(path, max_bytes=1024, on_chunk=fail_on_chunk)
    pipe.write("hello\n")

    with pytest.raises(RuntimeError, match="capture failed"):
        pipe.close()

    assert path.read_text(encoding="utf-8") == "hello\n"
