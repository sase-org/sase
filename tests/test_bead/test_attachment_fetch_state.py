"""Attachment-fetch state machine with a fake store.

Split from ``tests.test_bead.test_attachment_fetch``; the original module
re-exports these tests so its import path keeps working.
"""

from __future__ import annotations

import hashlib
import os
from pathlib import Path

import pytest

from sase.bead.attachments.blob_store import BlobStoreError

__all__ = [
    "test_fetch_mismatch_is_corrupt_and_not_installed",
    "test_fetch_mode_auto_installs_under_cap",
    "test_state_machine_remote_tombstone_is_purged",
    "test_state_machine_with_store",
    "test_state_machine_without_store_stays_two_state",
]


class _FakeStore:
    """Duck-typed stand-in for ``GitAttachmentStore`` (no subprocess)."""

    def __init__(
        self,
        objects: dict[str, bytes] | None = None,
        tombstones: set[str] | None = None,
    ) -> None:
        self.objects = dict(objects or {})
        self.tombstones = set(tombstones or {})

    def has(self, sha256: str) -> bool:
        return sha256 in self.objects

    def has_tombstone(self, sha256: str) -> bool:
        return sha256 in self.tombstones

    def get(self, sha256: str, dest: object, progress: object = None) -> None:
        from sase.bead.attachments.store import LocalAttachmentStore

        if sha256 not in self.objects:
            raise BlobStoreError(f"attachment {sha256[:16]}… is not in fake store")
        data = self.objects[sha256]
        if hashlib.sha256(data).hexdigest() != sha256:
            raise BlobStoreError(
                f"attachment {sha256[:16]}… failed digest verification",
                transient=False,
            )
        cas = LocalAttachmentStore(root=Path(str(dest)))
        cas.ensure_dirs()
        target = cas.object_path(sha256)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        os.chmod(target, 0o444)


def _cas_with(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, objects: dict[str, bytes]
) -> None:
    from sase.bead.attachments.store import LocalAttachmentStore

    monkeypatch.setenv("SASE_HOME", str(tmp_path / "sase-home"))
    cas = LocalAttachmentStore()
    cas.ensure_dirs()
    for sha, data in objects.items():
        target = cas.object_path(sha)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        os.chmod(target, 0o444)


def test_state_machine_without_store_stays_two_state(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sase.bead.attachments.fetch import _FetchContext, attachment_state

    data = b"local only bytes"
    sha = hashlib.sha256(data).hexdigest()
    _cas_with(tmp_path, monkeypatch, {sha: data})
    context = _FetchContext(mode="auto")
    assert attachment_state("0" * 64, context=context) == "unavailable"
    assert attachment_state(sha, context=context) == "cached"
    assert attachment_state(sha, size_bytes=len(data), context=context) == "cached"


def test_state_machine_with_store(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sase.bead.attachments.fetch import _FetchContext, attachment_state
    from sase.bead.attachments.outbox import OutboxEntry

    remote_data = b"remote bytes here"
    remote_sha = hashlib.sha256(remote_data).hexdigest()
    local_data = b"mine, never pushed"
    local_sha = hashlib.sha256(local_data).hexdigest()
    queued_data = b"queued for upload"
    queued_sha = hashlib.sha256(queued_data).hexdigest()
    bad_data = b"tampered locally"
    bad_sha = hashlib.sha256(b"original bytes").hexdigest()
    gone_sha = hashlib.sha256(b"purged object").hexdigest()
    _cas_with(
        tmp_path,
        monkeypatch,
        {local_sha: local_data, queued_sha: queued_data, bad_sha: bad_data},
    )
    from sase.bead.attachments.store import LocalAttachmentStore

    tombstones = LocalAttachmentStore().tombstones_dir
    tombstones.mkdir(parents=True, exist_ok=True)
    (tombstones / gone_sha).write_text("{}", encoding="utf-8")

    store = _FakeStore(objects={remote_sha: remote_data, local_sha: local_data})
    context = _FetchContext(
        mode="never",
        store=store,
        outbox={
            queued_sha: OutboxEntry(
                digest=queued_sha, size_bytes=len(queued_data), origin="laptop"
            )
        },
        cap_bytes=8,
    )
    assert attachment_state(remote_sha, size_bytes=1024, context=context) == (
        "not_downloaded"
    )
    assert attachment_state(local_sha, size_bytes=len(local_data), context=context) == (
        "cached"
    )
    assert attachment_state(queued_sha, size_bytes=1, context=context) == (
        "pending_upload"
    )
    assert attachment_state("1" * 64, context=context) == "unavailable"
    assert attachment_state(bad_sha, size_bytes=1, context=context) == "corrupt"
    assert attachment_state(gone_sha, size_bytes=1, context=context) == "purged"
    for state in (
        attachment_state(remote_sha, size_bytes=1024, context=context),
        attachment_state("1" * 64, context=context),
    ):
        assert state != "remote"

    lone_data = b"only here"
    lone_sha = hashlib.sha256(lone_data).hexdigest()
    _cas_with(tmp_path, monkeypatch, {lone_sha: lone_data})
    lonely = _FetchContext(mode="never", store=_FakeStore(), cap_bytes=8)
    assert attachment_state(lone_sha, size_bytes=1, context=lonely) == "local_only"


def test_state_machine_remote_tombstone_is_purged(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sase.bead.attachments.fetch import _FetchContext, attachment_state

    sha = hashlib.sha256(b"purged upstream").hexdigest()
    _cas_with(tmp_path, monkeypatch, {})
    context = _FetchContext(
        mode="force", store=_FakeStore(tombstones={sha}), cap_bytes=8
    )
    assert attachment_state(sha, size_bytes=1, context=context) == "purged"


def test_fetch_mode_auto_installs_under_cap(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sase.bead.attachments.fetch import _FetchContext, attachment_state
    from sase.bead.attachments.store import LocalAttachmentStore

    data = b"small remote file"
    sha = hashlib.sha256(data).hexdigest()
    _cas_with(tmp_path, monkeypatch, {})
    context = _FetchContext(
        mode="auto", store=_FakeStore(objects={sha: data}), cap_bytes=1 << 20
    )
    assert attachment_state(sha, size_bytes=len(data), context=context) == "cached"
    assert LocalAttachmentStore().verify(sha)


def test_fetch_mismatch_is_corrupt_and_not_installed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sase.bead.attachments.fetch import _FetchContext, attachment_state
    from sase.bead.attachments.store import LocalAttachmentStore

    claimed = hashlib.sha256(b"real bytes").hexdigest()
    _cas_with(tmp_path, monkeypatch, {})
    context = _FetchContext(
        mode="force",
        store=_FakeStore(objects={claimed: b"tampered bytes"}),
        cap_bytes=1,
    )
    assert attachment_state(claimed, size_bytes=11, context=context) == "corrupt"
    assert not LocalAttachmentStore().has(claimed)
