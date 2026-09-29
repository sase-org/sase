"""Tests for the local content-addressed attachment store (phase cas)."""

from __future__ import annotations

import hashlib
import io
import os
import stat
import tracemalloc
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from sase.bead.attachments import (
    BlobStore,
    BlobStoreError,
    LocalAttachmentStore,
    ingest_path,
    ingest_stream,
    probe_image,
    validate_sha256,
)
from sase.bead.attachments.ingest import IngestError


@pytest.fixture()
def store(tmp_path: Path) -> LocalAttachmentStore:
    return LocalAttachmentStore(root=tmp_path / "attachments")


def _write(path: Path, data: bytes) -> Path:
    path.write_bytes(data)
    return path


def test_round_trip_random_binary(store: LocalAttachmentStore, tmp_path: Path) -> None:
    data = os.urandom(2 * 1024 * 1024 + 123)
    src = _write(tmp_path / "rand.bin", data)
    blob = ingest_path(src, store=store)
    assert blob.sha256 == hashlib.sha256(data).hexdigest()
    assert blob.size_bytes == len(data)
    assert blob.head == data[:4096]
    assert blob.object_path.read_bytes() == data
    assert store.has(blob.sha256)
    assert store.verify(blob.sha256)


def test_round_trip_nul_heavy(store: LocalAttachmentStore, tmp_path: Path) -> None:
    data = b"\x00" * 700_000 + os.urandom(1000) + b"\x00" * 500_000
    src = _write(tmp_path / "nul.bin", data)
    blob = ingest_path(src, store=store)
    assert blob.object_path.read_bytes() == data
    assert store.verify(blob.sha256)


def test_round_trip_non_utf8(store: LocalAttachmentStore, tmp_path: Path) -> None:
    data = bytes(range(256)) * 100 + b"\xff\xfe\x00\x80" * 500
    assert data[:100].find(b"\xff") == -1  # sanity: head holds invalid UTF-8
    with pytest.raises(UnicodeDecodeError):
        data.decode("utf-8")
    src = _write(tmp_path / "weird.bin", data)
    blob = ingest_path(src, store=store)
    assert blob.object_path.read_bytes() == data


def test_sparse_stays_sparse_and_bounded_memory(
    store: LocalAttachmentStore, tmp_path: Path
) -> None:
    apparent = 256 * 1024 * 1024
    src = tmp_path / "sparse.bin"
    with open(src, "wb") as handle:
        handle.write(os.urandom(4096))
        handle.seek(apparent // 2)
        handle.write(os.urandom(4096))
        handle.truncate(apparent)
    assert src.stat().st_size == apparent
    tracemalloc.start()
    try:
        blob = ingest_path(src, store=store)
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    assert blob.size_bytes == apparent
    assert peak < 64 * 1024 * 1024
    blocks_bytes = blob.object_path.stat().st_blocks * 512
    assert blocks_bytes < apparent // 2
    assert blob.object_path.stat().st_size == apparent


def test_concurrent_ingests_produce_one_object(
    store: LocalAttachmentStore, tmp_path: Path
) -> None:
    data = os.urandom(1024 * 1024)
    first = _write(tmp_path / "a.bin", data)
    second = _write(tmp_path / "b.bin", data)
    with ThreadPoolExecutor(max_workers=2) as pool:
        left, right = tuple(
            pool.map(lambda p: ingest_path(p, store=store), (first, second))
        )
    assert left.sha256 == right.sha256 == hashlib.sha256(data).hexdigest()
    assert left.object_path == right.object_path
    assert store.verify(left.sha256)


def test_mutated_source_is_detected(
    store: LocalAttachmentStore, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    src = _write(tmp_path / "shifty.bin", os.urandom(100_000))
    real_fstat = os.fstat
    calls = 0

    def flaky_fstat(fd: int) -> os.stat_result:
        nonlocal calls
        result = real_fstat(fd)
        calls += 1
        if calls > 1:
            # Pretend the file changed after the ingest pass started.
            return os.stat_result(
                (
                    result.st_mode,
                    result.st_ino,
                    result.st_dev,
                    result.st_nlink,
                    result.st_uid,
                    result.st_gid,
                    result.st_size + 1,
                    result.st_atime,
                    result.st_mtime,
                    result.st_ctime,
                )
            )
        return result

    monkeypatch.setattr(os, "fstat", flaky_fstat)
    with pytest.raises(IngestError, match="changed while attaching"):
        ingest_path(src, store=store)


def test_directories_and_fifos_are_refused(
    store: LocalAttachmentStore, tmp_path: Path
) -> None:
    with pytest.raises(IngestError, match="directory"):
        ingest_path(tmp_path, store=store)
    fifo = tmp_path / "pipe"
    os.mkfifo(fifo)
    with pytest.raises(IngestError, match="[Pp]ipe|FIFO"):
        ingest_path(fifo, store=store)


def test_missing_file_is_refused(store: LocalAttachmentStore, tmp_path: Path) -> None:
    with pytest.raises(IngestError, match="not found"):
        ingest_path(tmp_path / "nope.bin", store=store)


def test_stdin_ingest(store: LocalAttachmentStore) -> None:
    data = os.urandom(100_000) + b"\x00" * 10_000 + b"\xff\xfe\x80"
    blob = ingest_stream(io.BytesIO(data), store=store)
    assert blob.sha256 == hashlib.sha256(data).hexdigest()
    assert blob.size_bytes == len(data)
    assert blob.object_path.read_bytes() == data


def test_stream_progress_reports_bytes(
    store: LocalAttachmentStore, tmp_path: Path
) -> None:
    data = os.urandom(3 * 1024 * 1024)
    src = _write(tmp_path / "big.bin", data)
    seen: list[tuple[int, int | None]] = []
    blob = ingest_path(src, progress=lambda done, total: seen.append((done, total)))
    assert blob.sha256 == hashlib.sha256(data).hexdigest()
    assert seen
    assert seen[-1] == (len(data), len(data))


def test_views_keep_extension_and_objects_read_only(
    store: LocalAttachmentStore, tmp_path: Path
) -> None:
    src = _write(tmp_path / "shot.png", os.urandom(10_000))
    blob = ingest_path(src, store=store)
    first = store.materialize_view(blob.sha256, "shot.png")
    second = store.materialize_view(blob.sha256, "shot.png")
    assert first == second
    assert first.suffix == ".png"
    assert first.is_symlink()
    assert not os.path.isabs(os.readlink(first))
    assert first.resolve() == blob.object_path
    mode = stat.S_IMODE(blob.object_path.stat().st_mode)
    assert mode == 0o444


def test_view_requires_cached_object(store: LocalAttachmentStore) -> None:
    with pytest.raises(BlobStoreError, match="not cached"):
        store.materialize_view("e" * 64, "x.bin")
    with pytest.raises(ValueError, match="invalid attachment view name"):
        store.materialize_view("e" * 64, "../evil")
    with pytest.raises(ValueError, match="invalid sha256"):
        store.materialize_view("nope", "x.bin")


def test_verify_rejects_tampered_object(
    store: LocalAttachmentStore, tmp_path: Path
) -> None:
    src = _write(tmp_path / "t.bin", os.urandom(5000))
    blob = ingest_path(src, store=store)
    assert store.verify(blob.sha256)
    assert not store.verify("0" * 64)
    os.chmod(blob.object_path, 0o644)
    with open(blob.object_path, "ab") as handle:
        handle.write(b"tamper")
    assert not store.verify(blob.sha256)


def test_remove_drops_object_and_views(
    store: LocalAttachmentStore, tmp_path: Path
) -> None:
    src = _write(tmp_path / "r.bin", os.urandom(1000))
    blob = ingest_path(src, store=store)
    store.materialize_view(blob.sha256, "r.bin")
    assert store.remove(blob.sha256)
    assert not store.has(blob.sha256)
    assert not store.remove(blob.sha256)


def test_default_root_honors_sase_home(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sase.bead.attachments import default_store_root

    monkeypatch.setenv("SASE_HOME", str(tmp_path / "sase-home"))
    assert default_store_root() == tmp_path / "sase-home" / "attachments"


def test_validate_sha256() -> None:
    assert validate_sha256("a" * 64) == "a" * 64
    with pytest.raises(ValueError, match="invalid sha256"):
        validate_sha256("xyz")


def test_blob_store_error_transient_flag() -> None:
    assert BlobStoreError("down", transient=True).transient is True
    assert BlobStoreError("bad").transient is False


def test_blob_store_protocol_shape(tmp_path: Path) -> None:
    from pathlib import Path as _Path

    from sase.bead.attachments import ProgressCallback as _Progress

    class _MemoryStore:
        def __init__(self) -> None:
            self.blobs: dict[str, bytes] = {}

        @property
        def name(self) -> str:
            return "memory"

        def describe(self) -> str:
            return "in-memory test store"

        def has(self, sha256: str) -> bool:
            return sha256 in self.blobs

        def put(
            self,
            sha256: str,
            src: _Path,
            size_bytes: int,
            progress: _Progress | None = None,
        ) -> None:
            self.blobs[sha256] = src.read_bytes()

        def get(
            self,
            sha256: str,
            dest: _Path,
            progress: _Progress | None = None,
        ) -> None:
            dest.write_bytes(self.blobs[sha256])

        def delete(self, sha256: str) -> None:
            self.blobs.pop(sha256, None)

    candidate = _MemoryStore()
    assert isinstance(candidate, BlobStore)
    payload = tmp_path / "p.bin"
    payload.write_bytes(b"blob-bytes")
    candidate.put("digest", payload, payload.stat().st_size)
    assert candidate.has("digest")
    out = tmp_path / "out.bin"
    candidate.get("digest", out)
    assert out.read_bytes() == b"blob-bytes"
    candidate.delete("digest")
    assert not candidate.has("digest")


def test_probe_image_never_raises(tmp_path: Path) -> None:
    assert probe_image(tmp_path / "missing.png") is None
    svg = _write(tmp_path / "v.svg", b"<svg></svg>")
    assert probe_image(svg) is None
    text = _write(tmp_path / "n.txt", b"hello")
    assert probe_image(text) is None
