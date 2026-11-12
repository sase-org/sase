"""Existing-remote verification for the private attachment store (sase-1db).

The attachments-private remote is trusted on its configured role alone
unless something probes it: repo-init preflight only compared visibility
when creating a missing remote, ``put`` pushed to any configured origin,
and ``describe_label`` hard-coded "(private)". These tests pin the fix:

- pre-upload ``put`` on a private-layout store probes the clone origin
  once per process and refuses a public remote before any bytes move;
- ``describe_label`` derives its suffix from the probe instead of
  hard-coding "(private)".

All remotes are local ``file://`` bare repositories; the visibility
prober is injected, so no test touches the network.
"""

from __future__ import annotations

import hashlib
import subprocess
from pathlib import Path

import pytest

_GIT_TIMEOUT = 60.0


def _git(cwd: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
        timeout=_GIT_TIMEOUT,
    )


def _remote_has_tip(remote: Path) -> bool:
    """Return whether the remote bare repo has any commit on its HEAD."""
    probed = subprocess.run(
        ["git", "rev-parse", "--verify", "--quiet", "HEAD"],
        cwd=remote,
        check=False,
        capture_output=True,
        timeout=_GIT_TIMEOUT,
    )
    return probed.returncode == 0 and bool((probed.stdout or b"").strip())


@pytest.fixture()
def private_clone(tmp_path: Path) -> tuple[Path, Path]:
    """Return ``(remote, clone)``: bare remote plus a partial bare clone."""
    remote = tmp_path / "priv-remote.git"
    _git(tmp_path, "init", "--bare", "-b", "main", remote.name)
    _git(remote, "config", "uploadpack.allowFilter", "true")
    _git(remote, "config", "uploadpack.allowAnySHA1InWant", "true")
    clone = tmp_path / "priv-clone.git"
    _git(
        tmp_path,
        "clone",
        "--bare",
        "--filter=blob:none",
        f"file://{remote}",
        clone.name,
    )
    return remote, clone


@pytest.fixture(autouse=True)
def _fresh_private_verification(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Isolate the once-per-process probe memo between tests."""
    from sase.bead.attachments.git_store import writes as _writes_mod

    monkeypatch.setattr(_writes_mod, "_VERIFIED_PRIVATE_CLONES", {})


def _write_src(tmp_path: Path, name: str, data: bytes) -> tuple[Path, str, int]:
    src = tmp_path / name
    src.write_bytes(data)
    return src, hashlib.sha256(data).hexdigest(), len(data)


def test_private_put_refuses_public_remote_before_any_push(
    tmp_path: Path, private_clone: tuple[Path, Path]
) -> None:
    """A public probe fails closed: no bytes are written or pushed."""
    from sase.bead.attachments.blob_store import BlobStoreError
    from sase.bead.attachments.git_store import GitAttachmentStore
    from sase.bead.attachments.remote_visibility import set_remote_visibility_prober

    remote, clone = private_clone
    # Mirror production: the clone points at a hosted remote URL.
    _git(
        clone,
        "remote",
        "set-url",
        "origin",
        "https://github.com/acme/widget--attachments-private.git",
    )
    src, digest, size = _write_src(tmp_path, "secret.bin", b"secret private bytes")
    store = GitAttachmentStore(clone, "acme/widget--attachments-private (private)")
    set_remote_visibility_prober(lambda url: "public")
    try:
        with pytest.raises(BlobStoreError, match="refusing to upload private"):
            store.put(digest, src, size)
    finally:
        set_remote_visibility_prober(None)
    # Refused before any local write or push: the remote stays unborn.
    assert not store.has(digest)
    assert not _remote_has_tip(remote)


def test_private_put_probes_once_per_process(
    tmp_path: Path, private_clone: tuple[Path, Path]
) -> None:
    """The first upload probes; later uploads to the same clone do not."""
    from sase.bead.attachments.git_store import GitAttachmentStore
    from sase.bead.attachments.remote_visibility import set_remote_visibility_prober

    remote, clone = private_clone
    calls: list[str] = []

    def prober(url: str) -> str:
        calls.append(url)
        return "private"

    set_remote_visibility_prober(prober)
    try:
        store = GitAttachmentStore(clone, "acme/widget--attachments-private")
        for name in ("a.bin", "b.bin"):
            src, digest, size = _write_src(tmp_path, name, name.encode() * 64)
            store.put(digest, src, size)
            assert store.has(digest)
    finally:
        set_remote_visibility_prober(None)
    assert len(calls) == 1
    assert _remote_has_tip(remote)


def test_private_put_unknown_visibility_proceeds(
    tmp_path: Path, private_clone: tuple[Path, Path]
) -> None:
    """Unknown (offline, inconclusive) stays fail-open; labels carry honesty."""
    from sase.bead.attachments.git_store import GitAttachmentStore
    from sase.bead.attachments.remote_visibility import set_remote_visibility_prober

    remote, clone = private_clone
    src, digest, size = _write_src(tmp_path, "local.bin", b"offline bytes" * 8)
    store = GitAttachmentStore(clone, "acme/widget--attachments-private")
    set_remote_visibility_prober(lambda url: "unknown")
    try:
        store.put(digest, src, size)
    finally:
        set_remote_visibility_prober(None)
    assert store.has(digest)


def test_private_put_prober_error_proceeds_as_unknown(
    tmp_path: Path, private_clone: tuple[Path, Path]
) -> None:
    from sase.bead.attachments.git_store import GitAttachmentStore
    from sase.bead.attachments.remote_visibility import set_remote_visibility_prober

    remote, clone = private_clone
    src, digest, size = _write_src(tmp_path, "flaky.bin", b"flaky probe bytes" * 8)

    def prober(url: str) -> str:
        raise RuntimeError("probe exploded")

    store = GitAttachmentStore(clone, "acme/widget--attachments-private")
    set_remote_visibility_prober(prober)
    try:
        store.put(digest, src, size)
    finally:
        set_remote_visibility_prober(None)
    assert store.has(digest)


def test_public_layout_put_ignores_private_probe(
    tmp_path: Path, private_clone: tuple[Path, Path]
) -> None:
    """The gate covers private-layout stores only; public writes are public."""
    from sase.bead.attachments.git_store import GitAttachmentStore
    from sase.bead.attachments.remote_visibility import set_remote_visibility_prober

    remote, clone = private_clone
    src, digest, size = _write_src(tmp_path, "pub.bin", b"public bytes" * 8)
    store = GitAttachmentStore(
        clone, "acme/widget--attachments (public)", name="public", layout="public"
    )
    set_remote_visibility_prober(lambda url: "public")
    try:
        store.put(digest, src, size, mime_type="text/plain")
    finally:
        set_remote_visibility_prober(None)
    assert store.has(digest)


def _hosted_clone(tmp_path: Path, clone: Path) -> Path:
    _git(
        clone,
        "remote",
        "set-url",
        "origin",
        "https://github.com/acme/widget--attachments-private.git",
    )
    return clone


def test_describe_label_private_when_probe_says_private(
    tmp_path: Path, private_clone: tuple[Path, Path]
) -> None:
    from sase.bead.attachments.remote_visibility import set_remote_visibility_prober
    from sase.bead.attachments.upload.discovery import describe_label

    _, clone = private_clone
    set_remote_visibility_prober(lambda url: "private")
    try:
        assert describe_label(_hosted_clone(tmp_path, clone), "widget") == (
            "acme/widget--attachments-private (private)"
        )
    finally:
        set_remote_visibility_prober(None)


def test_describe_label_unverified_when_probe_says_unknown(
    tmp_path: Path, private_clone: tuple[Path, Path]
) -> None:
    from sase.bead.attachments.remote_visibility import set_remote_visibility_prober
    from sase.bead.attachments.upload.discovery import describe_label

    _, clone = private_clone
    set_remote_visibility_prober(lambda url: "unknown")
    try:
        assert describe_label(_hosted_clone(tmp_path, clone), "widget") == (
            "acme/widget--attachments-private (private, unverified)"
        )
    finally:
        set_remote_visibility_prober(None)


def test_describe_label_alarms_when_probe_says_public(
    tmp_path: Path, private_clone: tuple[Path, Path]
) -> None:
    from sase.bead.attachments.remote_visibility import set_remote_visibility_prober
    from sase.bead.attachments.upload.discovery import describe_label

    _, clone = private_clone
    set_remote_visibility_prober(lambda url: "public")
    try:
        assert describe_label(_hosted_clone(tmp_path, clone), "widget") == (
            "acme/widget--attachments-private (PUBLIC — not private!)"
        )
    finally:
        set_remote_visibility_prober(None)


def test_describe_label_public_audience_unchanged(
    tmp_path: Path, private_clone: tuple[Path, Path]
) -> None:
    from sase.bead.attachments.remote_visibility import set_remote_visibility_prober
    from sase.bead.attachments.upload.discovery import describe_label

    _, clone = private_clone
    set_remote_visibility_prober(lambda url: "public")
    try:
        assert describe_label(_hosted_clone(tmp_path, clone), "widget", "public") == (
            "acme/widget--attachments-private (public)"
        )
    finally:
        set_remote_visibility_prober(None)


def test_describe_label_unparseable_remote_is_unverified(
    tmp_path: Path, private_clone: tuple[Path, Path]
) -> None:
    """A file:// origin names no repo, so the label cannot claim private."""
    from sase.bead.attachments.upload.discovery import describe_label

    _, clone = private_clone
    assert describe_label(clone, "widget") == (
        "widget--attachments-private (private, unverified)"
    )
