"""Tests for the git-backed attachment blob store (phase git_store).

All remotes are local bare repositories; clones use ``file://`` URLs so the
``blob:none`` partial-clone filter is honored. No network and no GitHub.
"""

from __future__ import annotations

import hashlib
import os
import subprocess
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
import sase_core_rs

from sase.bead.attachments import (
    BlobStore,
    BlobStoreError,
    GitAttachmentStore,
    LocalAttachmentStore,
)
from sase.bead.attachments.git_store import store as git_store_module

_GIT_TIMEOUT = 60.0
_STORE_TIMEOUT = 60.0
_LABEL = "test-owner/test--attachments-private (private)"

_COMMIT_ENV = {
    "GIT_AUTHOR_NAME": "Tests",
    "GIT_AUTHOR_EMAIL": "tests@example.test",
    "GIT_COMMITTER_NAME": "Tests",
    "GIT_COMMITTER_EMAIL": "tests@example.test",
}


def git(cwd: Path, *args: str) -> subprocess.CompletedProcess[str]:
    """Run one git command in *cwd* and fail on a non-zero exit."""

    return subprocess.run(
        ["git", *args],
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
        timeout=_GIT_TIMEOUT,
    )


@pytest.fixture()
def pair(tmp_path: Path) -> tuple[Path, Path, Path]:
    """Return ``(remote, clone_a, clone_b)``: bare remote, two partial clones."""

    remote = tmp_path / "remote.git"
    git(tmp_path, "init", "--bare", "-b", "main", remote.name)
    git(remote, "config", "uploadpack.allowFilter", "true")
    git(remote, "config", "uploadpack.allowAnySHA1InWant", "true")
    clone_a = tmp_path / "a.git"
    clone_b = tmp_path / "b.git"
    git(
        tmp_path,
        "clone",
        "--bare",
        "--filter=blob:none",
        f"file://{remote}",
        clone_a.name,
    )
    git(
        tmp_path,
        "clone",
        "--bare",
        "--filter=blob:none",
        f"file://{remote}",
        clone_b.name,
    )
    return remote, clone_a, clone_b


def _store(repo: Path) -> GitAttachmentStore:
    return GitAttachmentStore(repo, _LABEL, fetch_timeout=_STORE_TIMEOUT)


def _write(path: Path, data: bytes) -> Path:
    path.write_bytes(data)
    return path


def test_protocol_shape_and_label(pair: tuple[Path, Path, Path]) -> None:
    _remote, clone_a, _clone_b = pair
    store = _store(clone_a)

    assert isinstance(store, BlobStore)
    assert store.name == "git"
    assert store.describe() == _LABEL


def test_constructor_rejects_non_repo(tmp_path: Path) -> None:
    with pytest.raises(BlobStoreError, match="not a bare git repository"):
        GitAttachmentStore(tmp_path / "missing", _LABEL)
    with pytest.raises(BlobStoreError, match="not a bare git repository"):
        GitAttachmentStore(tmp_path, _LABEL)


def test_round_trip_across_clones(
    pair: tuple[Path, Path, Path], tmp_path: Path
) -> None:
    _remote, clone_a, clone_b = pair
    data = os.urandom(50_000) + b"\x00" * 1000 + bytes(range(256))
    digest = hashlib.sha256(data).hexdigest()
    src = _write(tmp_path / "photo.png", data)
    seen: list[tuple[int, int | None]] = []

    _store(clone_a).put(
        digest, src, len(data), progress=lambda done, total: seen.append((done, total))
    )

    cas_root = tmp_path / "cas-b"
    _store(clone_b).get(digest, cas_root)
    cas = LocalAttachmentStore(root=cas_root)
    assert cas.object_path(digest).read_bytes() == data
    assert cas.verify(digest)
    view = cas.materialize_view(digest, "photo.png")
    assert view.suffix == ".png"
    assert view.resolve() == cas.object_path(digest)
    assert seen
    assert seen[-1] == (len(data), len(data))
    assert _store(clone_b).has(digest) is True


def test_has_fetches_once_per_process(
    pair: tuple[Path, Path, Path],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _remote, clone_a, clone_b = pair
    data = os.urandom(10_000)
    digest = hashlib.sha256(data).hexdigest()
    _store(clone_a).put(digest, _write(tmp_path / "a.bin", data), len(data))

    calls: list[list[str]] = []
    real = git_store_module.run_git

    def spy(
        args: list[str],
        *,
        cwd: Path,
        timeout: float,
        env: dict[str, str] | None = None,
    ) -> subprocess.CompletedProcess[str]:
        if args[:1] == ["fetch"]:
            calls.append(list(args))
        return real(args, cwd=cwd, timeout=timeout, env=env)

    monkeypatch.setattr(git_store_module, "run_git", spy)
    store_b = _store(clone_b)

    assert store_b.has(digest) is True
    assert len(calls) == 1
    assert store_b.has(digest) is True
    assert len(calls) == 1
    assert store_b.has("0" * 64) is False
    assert len(calls) == 1


def test_failed_fetch_keeps_cached_tip(
    pair: tuple[Path, Path, Path], tmp_path: Path
) -> None:
    remote, clone_a, _clone_b = pair
    data = os.urandom(10_000)
    digest = hashlib.sha256(data).hexdigest()
    _store(clone_a).put(digest, _write(tmp_path / "a.bin", data), len(data))

    clone_c = tmp_path / "c.git"
    git(
        tmp_path,
        "clone",
        "--bare",
        "--filter=blob:none",
        f"file://{remote}",
        clone_c.name,
    )
    git(clone_c, "remote", "set-url", "origin", "file:///nonexistent-remote.git")
    store_c = _store(clone_c)

    assert store_c.has(digest) is True
    assert store_c.has("0" * 64) is False


def test_second_put_of_same_digest_is_noop(
    pair: tuple[Path, Path, Path], tmp_path: Path
) -> None:
    _remote, clone_a, _clone_b = pair
    data = os.urandom(20_000)
    digest = hashlib.sha256(data).hexdigest()
    src = _write(tmp_path / "same.bin", data)
    store = _store(clone_a)

    store.put(digest, src, len(data))
    tip_before = git(clone_a, "rev-parse", "refs/heads/main").stdout.strip()
    store.put(digest, src, len(data))
    tip_after = git(clone_a, "rev-parse", "refs/heads/main").stdout.strip()

    assert tip_before == tip_after


def test_concurrent_puts_from_two_clones_converge(
    pair: tuple[Path, Path, Path], tmp_path: Path
) -> None:
    _remote, clone_a, clone_b = pair
    payloads = [os.urandom(300_000) + bytes([i]) * 1000 for i in range(2)]
    digests = [hashlib.sha256(data).hexdigest() for data in payloads]
    sources = [
        _write(tmp_path / f"side-{i}.bin", data) for i, data in enumerate(payloads)
    ]
    stores = [_store(clone_a), _store(clone_b)]

    def _put(item: tuple[GitAttachmentStore, str, Path, int]) -> None:
        store, digest, src, size = item
        store.put(digest, src, size)

    with ThreadPoolExecutor(max_workers=2) as pool:
        list(
            pool.map(
                _put,
                [
                    (stores[0], digests[0], sources[0], len(payloads[0])),
                    (stores[1], digests[1], sources[1], len(payloads[1])),
                ],
            )
        )

    for store in stores:
        for digest in digests:
            assert store.has(digest) is True
    cas_root = tmp_path / "cas-check"
    stores[0].get(digests[1], cas_root)
    assert (cas_root / "objects/sha256" / digests[1][:2] / digests[1]).read_bytes() == (
        payloads[1]
    )


def test_get_digest_mismatch_is_not_installed(
    pair: tuple[Path, Path, Path], tmp_path: Path
) -> None:
    _remote, clone_a, clone_b = pair
    claimed = hashlib.sha256(b"real bytes").hexdigest()
    relpath = sase_core_rs.artifact_object_relpath(claimed)
    bad_src = _write(tmp_path / "tampered.bin", b"tampered bytes")
    blob = git(clone_a, "hash-object", "-w", str(bad_src)).stdout.strip()
    env = {**os.environ, **_COMMIT_ENV, "GIT_INDEX_FILE": str(clone_a / "test-index")}

    def plumbing(*args: str) -> str:
        return subprocess.run(
            ["git", *args],
            cwd=clone_a,
            check=True,
            capture_output=True,
            text=True,
            timeout=_GIT_TIMEOUT,
            env=env,
        ).stdout.strip()

    plumbing("read-tree", "--empty")
    plumbing("update-index", "--add", "--cacheinfo", f"100644,{blob},{relpath}")
    tree = plumbing("write-tree")
    commit = plumbing("commit-tree", tree, "-m", f"chore(attachments): store {claimed}")
    plumbing("update-ref", "refs/heads/main", commit)
    git(clone_a, "push", "origin", "refs/heads/main:refs/heads/main")

    cas_root = tmp_path / "cas-b"
    with pytest.raises(BlobStoreError, match="digest verification") as excinfo:
        _store(clone_b).get(claimed, cas_root)

    assert excinfo.value.transient is False
    assert not (cas_root / "objects/sha256" / claimed[:2] / claimed).exists()


def test_commit_messages_carry_digest_without_filename(
    pair: tuple[Path, Path, Path], tmp_path: Path
) -> None:
    _remote, clone_a, _clone_b = pair
    names = ["secret-photo.png", "field-notes.txt"]
    digests = []
    for name in names:
        data = os.urandom(5000) + name.encode()
        digest = hashlib.sha256(data).hexdigest()
        digests.append(digest)
        _store(clone_a).put(digest, _write(tmp_path / name, data), len(data))

    messages = git(clone_a, "log", "--format=%B", "refs/heads/main").stdout
    for digest, name in zip(digests, names, strict=True):
        assert digest in messages
        assert name not in messages


def test_put_refuses_wrong_bytes_and_bad_digest(
    pair: tuple[Path, Path, Path], tmp_path: Path
) -> None:
    _remote, clone_a, _clone_b = pair
    src = _write(tmp_path / "actual.bin", os.urandom(1000))
    store = _store(clone_a)

    with pytest.raises(BlobStoreError, match="not .*"):
        store.put("f" * 64, src, len(src.read_bytes()))
    with pytest.raises(ValueError, match="invalid sha256"):
        store.put("nope", src, 8)
    probe = subprocess.run(
        ["git", "rev-parse", "--verify", "--quiet", "refs/heads/main"],
        cwd=clone_a,
        capture_output=True,
        text=True,
        timeout=_GIT_TIMEOUT,
    )
    assert probe.returncode != 0


def test_delete_removes_without_tombstone_and_noops_when_absent(
    pair: tuple[Path, Path, Path], tmp_path: Path
) -> None:
    _remote, clone_a, clone_b = pair
    kept = os.urandom(8000)
    dropped = os.urandom(8000)
    kept_digest = hashlib.sha256(kept).hexdigest()
    dropped_digest = hashlib.sha256(dropped).hexdigest()
    store_a = _store(clone_a)
    store_a.put(kept_digest, _write(tmp_path / "kept.bin", kept), len(kept))
    store_a.put(dropped_digest, _write(tmp_path / "dropped.bin", dropped), len(dropped))

    store_a.delete(dropped_digest)
    store_a.delete(dropped_digest)
    store_a.delete("1" * 64)

    assert store_a.has(kept_digest) is True
    assert store_a.has(dropped_digest) is False
    with pytest.raises(BlobStoreError, match="not in"):
        _store(clone_b).get(dropped_digest, tmp_path / "cas-b")
    tracked = git(clone_a, "ls-tree", "-r", "--name-only", "refs/heads/main").stdout
    assert "tombstone" not in tracked


def test_canonical_archive_object_digest_pins_shared_rule() -> None:
    from sase.agents_sync.prompt_archive.archive_objects import (
        canonical_archive_object_digest,
    )

    digest = hashlib.sha256(b"shared rule").hexdigest()
    assert (
        canonical_archive_object_digest(sase_core_rs.artifact_object_relpath(digest))
        == digest
    )
    assert canonical_archive_object_digest("files/objects/stray.txt") is None
    assert (
        canonical_archive_object_digest(f"files/objects/sha256/ff/{'0' * 64}") is None
    )
