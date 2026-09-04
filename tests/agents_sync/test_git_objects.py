from __future__ import annotations

from pathlib import Path
import subprocess

import pytest

from sase.agents_sync.git_objects import (
    _CatFileBatch,
    _CatFileStream,
    _CatFileStreamClosed,
)
from sase.agents_sync.io import AgentsSyncFormatError


class _FakePipe:
    def __init__(self, data: bytes = b"", *, chunk_size: int | None = None) -> None:
        self._data = data
        self._pos = 0
        self.chunk_size = chunk_size
        self.writes: list[bytes] = []
        self.read_requests: list[int] = []
        self.read1_requests: list[int] = []

    def write(self, data: bytes) -> int:
        self.writes.append(data)
        return len(data)

    def flush(self) -> None:
        return None

    def close(self) -> None:
        return None

    def read(self, n: int = -1) -> bytes:
        self.read_requests.append(n)
        take = len(self._data) - self._pos if n < 0 else n
        if self.chunk_size is not None:
            take = min(take, self.chunk_size)
        return self._take(take)

    def read1(self, n: int = -1) -> bytes:
        take = len(self._data) - self._pos if n < 0 else n
        if self.chunk_size is not None:
            take = min(take, self.chunk_size)
        self.read1_requests.append(take)
        return self._take(take)

    def _take(self, n: int) -> bytes:
        remaining = len(self._data) - self._pos
        n = max(0, min(n, remaining))
        out = self._data[self._pos : self._pos + n]
        self._pos += n
        return out


class _FakeProcess:
    def __init__(self, stdout_data: bytes, *, chunk_size: int | None = None) -> None:
        self.stdin = _FakePipe()
        self.stdout = _FakePipe(stdout_data, chunk_size=chunk_size)
        self.stderr = _FakePipe()
        self.pid = 0
        self.returncode: int | None = None

    def poll(self) -> int | None:
        return self.returncode

    def wait(self, timeout: float | None = None) -> int:
        self.returncode = 0
        return 0


def _install_fake_process(
    monkeypatch: pytest.MonkeyPatch, process: _FakeProcess
) -> None:
    monkeypatch.setattr(
        subprocess,
        "Popen",
        lambda *args, **kwargs: process,
    )


def test_read_until_nul_uses_chunked_read1_not_single_bytes() -> None:
    pipe = _FakePipe(b"abc blob 4\0body\0", chunk_size=64)
    stream = _CatFileStream(pipe)

    assert stream.read_until_nul() == b"abc blob 4"
    assert stream.read_exact(4) == b"body"
    assert stream.read_exact(1) == b"\0"
    assert pipe.read1_requests
    assert 1 not in pipe.read1_requests
    assert 1 not in pipe.read_requests


def test_read_until_nul_keeps_body_bytes_that_arrived_with_the_header() -> None:
    pipe = _FakePipe(b"deadbeef blob 5\0hello\0")
    stream = _CatFileStream(pipe)

    assert stream.read_until_nul() == b"deadbeef blob 5"
    assert stream.read_exact(5) == b"hello"
    assert stream.read_exact(1) == b"\0"
    assert pipe.read_requests == []


def test_read_exact_reassembles_a_body_split_across_blocking_reads() -> None:
    pipe = _FakePipe(b"sha blob 6\0abcdef\0", chunk_size=4)
    stream = _CatFileStream(pipe)

    assert stream.read_until_nul() == b"sha blob 6"
    assert stream.read_exact(6) == b"abcdef"
    assert stream.read_exact(1) == b"\0"


def test_read_until_nul_rejects_a_header_without_nul() -> None:
    stream = _CatFileStream(_FakePipe(b"not-a-header" * 400))
    with pytest.raises(AgentsSyncFormatError, match="header is too large"):
        stream.read_until_nul()


def test_read_until_nul_raises_when_the_pipe_closes() -> None:
    stream = _CatFileStream(_FakePipe(b""))
    with pytest.raises(_CatFileStreamClosed):
        stream.read_until_nul()


def test_read_blob_preserves_leftover_bytes_after_the_header_nul(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    process = _FakeProcess(b"abc123 blob 5\0hello\0")
    _install_fake_process(monkeypatch, process)
    batch = _CatFileBatch(tmp_path)

    assert batch.read_blob("abc123", relative="users/a.json", maximum=32) == b"hello"
    assert process.stdin.writes == [b"abc123\0"]


def test_read_blob_reads_a_body_that_arrives_in_short_chunks(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    payload = b"0123456789abcdef"
    header = f"sha blob {len(payload)}".encode("ascii")
    process = _FakeProcess(header + b"\0" + payload + b"\0", chunk_size=3)
    _install_fake_process(monkeypatch, process)
    batch = _CatFileBatch(tmp_path)

    assert batch.read_blob("sha", relative="chat.md", maximum=64) == payload


def test_read_blob_missing_object_does_not_consume_a_body(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    process = _FakeProcess(b"sha missing\0")
    _install_fake_process(monkeypatch, process)
    batch = _CatFileBatch(tmp_path)

    with pytest.raises(AgentsSyncFormatError, match="could not read fetched object"):
        batch.read_blob("sha", relative="gone.json", maximum=16)


def test_read_blob_drains_an_oversized_object_before_the_next_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    first = b"sha1 blob 8\0overflow\0"
    second = b"sha2 blob 3\0ok!\0"
    process = _FakeProcess(first + second)
    _install_fake_process(monkeypatch, process)
    batch = _CatFileBatch(tmp_path)

    with pytest.raises(AgentsSyncFormatError, match="exceeds the byte limit"):
        batch.read_blob("sha1", relative="big.bin", maximum=4)
    assert batch.read_blob("sha2", relative="ok.bin", maximum=8) == b"ok!"


def test_read_blob_drains_a_non_blob_object(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    tree = b"sha tree 4\0abcd\0"
    blob = b"sha blob 2\0hi\0"
    process = _FakeProcess(tree + blob)
    _install_fake_process(monkeypatch, process)
    batch = _CatFileBatch(tmp_path)

    with pytest.raises(AgentsSyncFormatError, match="is a tree, not a blob"):
        batch.read_blob("sha", relative="path", maximum=16)
    assert batch.read_blob("sha", relative="path", maximum=16) == b"hi"


def test_read_blob_reports_a_closed_stream_when_the_body_is_short(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    process = _FakeProcess(b"sha blob 8\0short")
    _install_fake_process(monkeypatch, process)
    batch = _CatFileBatch(tmp_path)

    with pytest.raises(AgentsSyncFormatError, match="could not read fetched object"):
        batch.read_blob("sha", relative="cut.bin", maximum=32)
