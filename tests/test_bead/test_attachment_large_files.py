"""Phase large_files: rclone large tier, background uploads, progress.

The rclone tests use a local-path remote (no daemon, no network) and skip
when the ``rclone`` binary is absent. The sparse end-to-end test moves a
multi-hundred-MiB file attach → upload → fetch across two SASE homes in
bounded memory and (nearly) no disk.
"""

from __future__ import annotations

import hashlib
import os
import shutil
import sys
import tracemalloc
from pathlib import Path
from types import SimpleNamespace

import pytest

from sase.bead.attachments.outbox import OutboxEntry, enqueue_outbox, read_outbox

rclone = pytest.mark.skipif(
    shutil.which("rclone") is None, reason="rclone binary is not installed"
)

_APPARENT_BYTES = 300 * 1024 * 1024


def _isolate_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point SASE_HOME at a scratch dir; return it."""
    home = tmp_path / "sase-home"
    monkeypatch.setenv("SASE_HOME", str(home))
    return home


def _large_config(
    monkeypatch: pytest.MonkeyPatch, remote: Path, max_bytes: int
) -> None:
    """Serve ``large_store`` from the merged config."""
    import sase.bead.config as bead_config

    monkeypatch.setattr(
        bead_config,
        "load_merged_config",
        lambda: {
            "bead": {
                "attachments": {
                    "large_store": {
                        "remote": str(remote),
                        "max_bytes": max_bytes,
                    },
                }
            }
        },
    )


def _sparse_file(path: Path, apparent: int = _APPARENT_BYTES) -> Path:
    """Create a sparse file reading as zeros with a nonzero tail byte."""
    with open(path, "wb") as handle:
        handle.seek(apparent - 1)
        handle.write(b"\x01")
    return path


def _disk_bytes(path: Path) -> int:
    return os.stat(path).st_blocks * 512


# -- config -------------------------------------------------------------


def test_large_store_defaults_to_none_and_threshold_64mib(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import sase.bead.config as bead_config

    monkeypatch.setattr(bead_config, "load_merged_config", lambda: {})
    assert bead_config.get_attachment_large_store() is None
    assert bead_config.get_attachment_background_upload_min_bytes() == 67108864


def test_large_store_fail_open(monkeypatch: pytest.MonkeyPatch) -> None:
    import sase.bead.config as bead_config

    for attachments in (
        {"large_store": {"max_bytes": 10}},
        {"large_store": "athena-sftp:attachments"},
        {"large_store": {"remote": "  ", "max_bytes": 10}},
        {"background_upload_min_bytes": 0},
        {"background_upload_min_bytes": True},
    ):
        monkeypatch.setattr(
            bead_config,
            "load_merged_config",
            lambda attachments=attachments: {"bead": {"attachments": attachments}},
        )
        assert bead_config.get_attachment_large_store() is None
        assert bead_config.get_attachment_background_upload_min_bytes() == 67108864


def test_large_store_parses_remote_and_cap(monkeypatch: pytest.MonkeyPatch) -> None:
    import sase.bead.config as bead_config

    monkeypatch.setattr(
        bead_config,
        "load_merged_config",
        lambda: {
            "bead": {
                "attachments": {
                    "large_store": {
                        "remote": "athena-sftp:attachments",
                        "max_bytes": 100,
                    }
                }
            }
        },
    )
    assert bead_config.get_attachment_large_store() == {
        "remote": "athena-sftp:attachments",
        "max_bytes": 100,
    }


# -- tier boundaries ----------------------------------------------------


def test_tier_boundaries_route_at_exact_caps(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sase.bead.attachments.upload import decide_placement

    monkeypatch.setattr(sys.stdin, "isatty", lambda: False)
    tiers = [
        {"name": "git", "max_bytes": 50},
        {"name": "large", "max_bytes": 200},
    ]
    assert (
        decide_placement(
            [{"name": "a", "size_bytes": 50}],
            tiers,
            local_only=False,
            require_upload=False,
        )
        == "git"
    )
    assert (
        decide_placement(
            [{"name": "a", "size_bytes": 51}],
            tiers,
            local_only=False,
            require_upload=False,
        )
        == "large"
    )
    assert (
        decide_placement(
            [{"name": "a", "size_bytes": 200}],
            tiers,
            local_only=False,
            require_upload=False,
        )
        == "large"
    )
    assert (
        decide_placement(
            [
                {"name": "a", "size_bytes": 50},
                {"name": "b", "size_bytes": 51},
            ],
            tiers,
            local_only=False,
            require_upload=False,
        )
        == "mixed"
    )


def test_over_large_cap_fails_before_any_write(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sase.bead.attachments.upload import (
        AttachmentTooLargeError,
        decide_placement,
    )

    monkeypatch.setattr(sys.stdin, "isatty", lambda: False)
    tiers = [
        {"name": "git", "max_bytes": 50},
        {"name": "large", "max_bytes": 200},
    ]
    with pytest.raises(AttachmentTooLargeError, match="-L"):
        decide_placement(
            [{"name": "dump.core", "size_bytes": 201}],
            tiers,
            local_only=False,
            require_upload=False,
        )


def test_no_tier_is_no_store_unless_require_upload(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sase.bead.attachments.upload import (
        AttachmentStoreMissingError,
        decide_placement,
    )

    wire = [{"name": "a", "size_bytes": 10}]
    assert (
        decide_placement(wire, [], local_only=False, require_upload=False) == "no_store"
    )
    with pytest.raises(AttachmentStoreMissingError):
        decide_placement(wire, [], local_only=False, require_upload=True)


# -- rclone store -------------------------------------------------------


@rclone
def test_rclone_roundtrip_on_local_remote(tmp_path: Path) -> None:
    from sase.bead.attachments.blob_store import BlobStoreError
    from sase.bead.attachments.rclone_store import RcloneAttachmentStore
    from sase.bead.attachments.store import LocalAttachmentStore

    remote = tmp_path / "large-remote"
    remote.mkdir()
    store = RcloneAttachmentStore(str(remote), str(remote))
    assert store.name == "large"

    data = os.urandom(3 * 1024 * 1024)
    sha = hashlib.sha256(data).hexdigest()
    src = tmp_path / "src.bin"
    src.write_bytes(data)

    assert store.has(sha) is False
    store.put(sha, src, len(data))
    assert store.has(sha) is True
    assert store.has_tombstone(sha) is False

    cas = LocalAttachmentStore(root=tmp_path / "cas")
    store.get(sha, cas.root)
    assert cas.verify(sha)
    assert cas.object_path(sha).read_bytes() == data

    store.delete(sha)
    assert store.has(sha) is False
    store.delete(sha)  # Absent deletes are a no-op.

    with pytest.raises(BlobStoreError, match="not a regular file"):
        store.put(sha, tmp_path, 0)


@rclone
def test_rclone_get_detects_tampered_remote(tmp_path: Path) -> None:
    from sase.bead.attachments.blob_store import BlobStoreError
    from sase.bead.attachments.rclone_store import RcloneAttachmentStore
    from sase.bead.attachments.store import LocalAttachmentStore

    remote = tmp_path / "large-remote"
    remote.mkdir()
    store = RcloneAttachmentStore(str(remote), str(remote))

    data = os.urandom(1024 * 1024)
    sha = hashlib.sha256(data).hexdigest()
    src = tmp_path / "src.bin"
    src.write_bytes(data)
    store.put(sha, src, len(data))

    planted = remote / "files" / "objects" / "sha256" / sha[:2] / sha
    planted.write_bytes(b"tampered" + planted.read_bytes()[8:])

    cas = LocalAttachmentStore(root=tmp_path / "cas")
    with pytest.raises(BlobStoreError, match="[Dd]igest|mismatch|verification"):
        store.get(sha, cas.root)
    assert not cas.has(sha)


def test_rclone_missing_binary_is_a_clear_error(tmp_path: Path) -> None:
    from sase.bead.attachments.blob_store import BlobStoreError
    from sase.bead.attachments.rclone_store import RcloneAttachmentStore

    store = RcloneAttachmentStore(
        str(tmp_path), str(tmp_path), rclone_binary_name="no-such-rclone-binary"
    )
    with pytest.raises(BlobStoreError, match="rclone"):
        store.has("0" * 64)


# -- sparse multi-hundred-MiB end to end ---------------------------------


@rclone
def test_sparse_multihundred_mib_attach_upload_fetch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import sase.bead.config as bead_config
    from sase.bead.attachments.ingest import ingest_path
    from sase.bead.attachments.rclone_store import RcloneAttachmentStore
    from sase.bead.attachments.store import LocalAttachmentStore

    _isolate_home(tmp_path, monkeypatch)
    source = _sparse_file(tmp_path / "dump.core")
    assert source.stat().st_size == _APPARENT_BYTES
    assert _disk_bytes(source) < 8 * 1024 * 1024

    tracemalloc.start()
    try:
        blob = ingest_path(source)
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    assert peak < 32 * 1024 * 1024
    assert blob.size_bytes == _APPARENT_BYTES
    assert _disk_bytes(blob.object_path) < 8 * 1024 * 1024

    remote = tmp_path / "large-remote"
    remote.mkdir()
    monkeypatch.setattr(
        bead_config,
        "load_merged_config",
        lambda: {
            "bead": {
                "attachments": {
                    "large_store": {
                        "remote": str(remote),
                        "max_bytes": 2 * 1024 * 1024 * 1024,
                    }
                }
            }
        },
    )
    store = RcloneAttachmentStore(str(remote), str(remote))
    store.put(blob.sha256, blob.object_path, blob.size_bytes)
    assert store.has(blob.sha256) is True

    # A second home fetches byte-exact bytes from the remote alone.
    second = LocalAttachmentStore(root=tmp_path / "second-home" / "attachments")
    store.get(blob.sha256, second.root)
    fetched = second.object_path(blob.sha256)
    assert fetched.stat().st_size == _APPARENT_BYTES
    assert second.verify(blob.sha256)
    digest = hashlib.sha256()
    with open(fetched, "rb") as handle:
        while chunk := handle.read(1 << 20):
            digest.update(chunk)
    assert digest.hexdigest() == blob.sha256


# -- background uploads --------------------------------------------------


def test_background_threshold_and_echo_shape() -> None:
    from sase.bead.attachments.background import (
        rewrite_echo_for_background,
        should_background,
    )

    assert should_background(67108864 - 1) is False
    assert should_background(67108864) is True
    rows = ["\u25a1 dump.core  text/plain \u00b7 70 MiB"]
    rewrite_echo_for_background(
        rows, [{"name": "dump.core", "size_bytes": 70 * 1024 * 1024}]
    )
    assert rows[0].endswith(
        "\u21e1 uploading in background (70 MiB) \u2014 sase bead attachment push"
    )


@rclone
def test_background_queue_drains_after_simulated_crash(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import sase.bead.attachments.background as background
    import sase.bead.attachments.upload as upload
    from sase.bead.attachments.store import LocalAttachmentStore

    _isolate_home(tmp_path, monkeypatch)
    remote = tmp_path / "large-remote"
    remote.mkdir()
    _large_config(monkeypatch, remote, 2 * 1024 * 1024 * 1024)
    monkeypatch.setattr(
        "sase.bead.attachments.upload.resolve_project_key",
        lambda _context=None: "test-project",
    )
    monkeypatch.setattr(
        "sase.bead.attachments.upload.discover_shared_store",
        lambda _context=None: None,
    )
    monkeypatch.setattr(
        "sase.bead.config.get_attachment_background_upload_min_bytes",
        lambda: 1024,
    )
    launched: list[str] = []
    monkeypatch.setattr(
        background,
        "launch_background_drain",
        lambda project_key: launched.append(project_key) or 4242,
    )

    data = os.urandom(4096)
    src = tmp_path / "big.bin"
    src.write_bytes(data)
    cas = LocalAttachmentStore()
    from sase.bead.attachments.ingest import ingest_path

    blob = ingest_path(src, store=cas)
    wire = {
        "name": "big.bin",
        "sha256": blob.sha256,
        "size_bytes": blob.size_bytes,
        "mime_type": "application/octet-stream",
    }
    stores = upload.discover_stores(None)
    assert set(stores) == {"large"}

    mutation = SimpleNamespace()
    echo_rows = ["\u25c7 big.bin  application/octet-stream \u00b7 4 KiB"]
    upload.post_write_queue(
        mutation,
        [wire],
        echo_rows,
        placement="large",
        stores=stores,
        project_key="test-project",
        require_upload=False,
    )
    queued = mutation.pending_attachment_uploads
    assert len(queued) == 1
    assert queued[0]["background"] is True
    assert queued[0]["store_name"] == "large"

    # Post-commit: the worker is launched and the echo names it. The
    # process then "crashes": entries stay in the durable outbox.
    upload.run_pending_uploads(mutation)
    assert launched == ["test-project"]
    assert "uploading in background" in echo_rows[0]
    entries = read_outbox("test-project")
    assert [entry.digest for entry in entries] == [blob.sha256]
    assert entries[0].store == "large"

    # The next worker run (or push) drains the leftovers.
    assert background.main(["test-project"]) == 0
    assert read_outbox("test-project") == []
    assert stores["large"].has(blob.sha256) is True
    assert background.main(["test-project"]) == 0


@rclone
def test_push_drains_large_outbox_with_progress(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import sase.bead.attachments.background as background
    from sase.bead.attachments.ingest import ingest_path
    from sase.bead.attachments.store import LocalAttachmentStore

    _isolate_home(tmp_path, monkeypatch)
    remote = tmp_path / "large-remote"
    remote.mkdir()
    _large_config(monkeypatch, remote, 2 * 1024 * 1024 * 1024)

    data = os.urandom(2048)
    src = tmp_path / "big.bin"
    src.write_bytes(data)
    blob = ingest_path(src, store=LocalAttachmentStore())
    enqueue_outbox(
        "test-project",
        [
            OutboxEntry(
                digest=blob.sha256,
                size_bytes=blob.size_bytes,
                store="large",
            )
        ],
    )
    drained, remaining = background.drain_project_outbox(
        "test-project", time_bound_seconds=120.0, progress=True
    )
    assert (drained, remaining) == (1, 0)


# -- progress ------------------------------------------------------------


def test_progress_stays_quiet_below_threshold_or_off_tty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sase.bead.attachments.progress import (
        PROGRESS_MIN_BYTES,
        progress_allowed,
        transfer_progress,
    )

    assert PROGRESS_MIN_BYTES == 8 * 1024 * 1024
    assert progress_allowed(None) is False
    assert progress_allowed(PROGRESS_MIN_BYTES - 1) is False
    monkeypatch.setenv("SASE_AGENT", "1")
    assert progress_allowed(64 * 1024 * 1024) is False
    monkeypatch.delenv("SASE_AGENT")
    # pytest captures stderr: never a TTY here.
    assert progress_allowed(64 * 1024 * 1024) is False
    with transfer_progress("label", 64 * 1024 * 1024) as bar:
        assert bar is None
    with transfer_progress("label", 1024) as bar:
        assert bar is None


def test_progress_draws_on_a_tty(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    import sys

    from sase.bead.attachments.progress import progress_allowed, transfer_progress

    monkeypatch.delenv("SASE_AGENT", raising=False)
    monkeypatch.setattr(sys.stderr, "isatty", lambda: True)
    assert progress_allowed(9 * 1024 * 1024) is True
    with transfer_progress("big.bin", 9 * 1024 * 1024) as bar:
        assert bar is not None
        bar(1024, 9 * 1024 * 1024)
        bar(9 * 1024 * 1024, 9 * 1024 * 1024)
    capsys.readouterr()
