"""Public attachments sidecar, routing, and anonymous reads (sase-1d5.4).

Two homes are local ``file://`` bare remotes and two ``SASE_HOME``
directories. The visibility prober is injected; no real GitHub remotes and
no network.
"""

from __future__ import annotations

import hashlib
import subprocess
from pathlib import Path

import pytest

_GIT_TIMEOUT = 60.0

_COMMIT_ENV = {
    "GIT_AUTHOR_NAME": "Tests",
    "GIT_AUTHOR_EMAIL": "tests@example.test",
    "GIT_COMMITTER_NAME": "Tests",
    "GIT_COMMITTER_EMAIL": "tests@example.test",
}


def _git(cwd: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
        timeout=_GIT_TIMEOUT,
    )


@pytest.fixture()
def remote(tmp_path: Path) -> Path:
    path = tmp_path / "public-remote.git"
    _git(tmp_path, "init", "--bare", "-b", "main", path.name)
    _git(path, "config", "uploadpack.allowFilter", "true")
    _git(path, "config", "uploadpack.allowAnySHA1InWant", "true")
    return path


@pytest.fixture()
def private_remote(tmp_path: Path) -> Path:
    path = tmp_path / "private-remote.git"
    _git(tmp_path, "init", "--bare", "-b", "main", path.name)
    _git(path, "config", "uploadpack.allowFilter", "true")
    _git(path, "config", "uploadpack.allowAnySHA1InWant", "true")
    return path


def _plant_clone(home: Path, remote: Path, role: str) -> Path:
    from sase.core.paths import sase_projects_dir

    clone = sase_projects_dir() / "test-project" / "repos" / role
    clone.parent.mkdir(parents=True, exist_ok=True)
    if clone.exists():
        return clone
    subprocess.run(
        [
            "git",
            "clone",
            "--bare",
            "--filter=blob:none",
            f"file://{remote}",
            str(clone),
        ],
        cwd=home,
        check=True,
        capture_output=True,
        text=True,
        timeout=_GIT_TIMEOUT,
    )
    return clone


def _use_home(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, name: str) -> Path:
    home = tmp_path / name
    home.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("SASE_HOME", str(home))
    return home


@pytest.fixture()
def public_prober(monkeypatch: pytest.MonkeyPatch):
    from sase.bead.attachments.remote_visibility import (
        set_remote_visibility_prober,
    )

    set_remote_visibility_prober(lambda url: "public")
    yield
    set_remote_visibility_prober(None)


def _clear_fetch_cache() -> None:
    try:
        from sase.bead.attachments.git_store import reads as _reads_mod

        _reads_mod._FETCHED_REPOS.clear()
    except Exception:
        pass
    try:
        from sase.bead.attachments.upload import discovery as _disc

        _disc._PUBLIC_MATERIALIZATION_ATTEMPTED.clear()
    except Exception:
        pass


def test_public_object_read_on_second_home_with_only_public_remote(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    public_prober,
    remote: Path,
) -> None:
    """Home A writes public; home B with only the public remote reads it."""
    from sase.bead.attachments.git_store import GitAttachmentStore
    from sase.bead.attachments.store import LocalAttachmentStore

    home_a = _use_home(monkeypatch, tmp_path, "sase-home-a")
    clone_a = _plant_clone(home_a, remote, "attachments")
    _clear_fetch_cache()
    data = b"public bytes for two homes"
    digest = hashlib.sha256(data).hexdigest()
    src = tmp_path / "payload.bin"
    src.write_bytes(data)
    store_a = GitAttachmentStore(
        clone_a, "owner/repo (public)", name="public", layout="public"
    )
    store_a.put(digest, src, len(data), mime_type="text/plain")

    home_b = _use_home(monkeypatch, tmp_path, "sase-home-b")
    _plant_clone(home_b, remote, "attachments")
    _clear_fetch_cache()
    # No private clone on home B.
    from sase.core.paths import sase_projects_dir

    assert not (
        sase_projects_dir() / "test-project" / "repos" / "attachments-private"
    ).exists()
    clone_b = sase_projects_dir() / "test-project" / "repos" / "attachments"
    store_b = GitAttachmentStore(
        clone_b, "owner/repo (public)", name="public", layout="public"
    )
    assert store_b.has(digest)
    target = tmp_path / "cas-b"
    store_b.get(digest, target)
    assert (target / "objects" / "sha256" / digest[:2] / digest).read_bytes() == data


def test_private_object_never_on_public_remote(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, public_prober, remote: Path
) -> None:
    from sase.bead.attachments.git_store import GitAttachmentStore

    home_a = _use_home(monkeypatch, tmp_path, "sase-home-a")
    public_clone = _plant_clone(home_a, remote, "attachments")
    _clear_fetch_cache()
    data = b"private bytes stay private"
    digest = hashlib.sha256(data).hexdigest()
    src = tmp_path / "private.bin"
    src.write_bytes(data)
    # Private placement never touches the public store: simulate by writing
    # only to a private clone and asserting the public tree lacks it.
    import tempfile

    with tempfile.TemporaryDirectory() as td:
        priv_remote = Path(td) / "priv.git"
        _git(Path(td), "init", "--bare", "-b", "main", "priv.git")
        priv_clone = _plant_clone(home_a, priv_remote, "attachments-private")
        priv = GitAttachmentStore(priv_clone, "owner/priv (private)")
        priv.put(digest, src, len(data))
        assert priv.has(digest)
    public = GitAttachmentStore(
        public_clone, "owner/repo (public)", name="public", layout="public"
    )
    assert not public.has(digest)


def test_over_cap_public_never_on_public_remote(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, public_prober, remote: Path
) -> None:
    from sase.bead.attachments.git_store import GitAttachmentStore
    from sase.bead.config import get_attachment_public_max_bytes

    home_a = _use_home(monkeypatch, tmp_path, "sase-home-a")
    clone = _plant_clone(home_a, remote, "attachments")
    _clear_fetch_cache()
    cap = get_attachment_public_max_bytes()
    data = b"x" * (cap + 1)
    digest = hashlib.sha256(data).hexdigest()
    src = tmp_path / "big.bin"
    src.write_bytes(data)
    # Placement for an over-cap public wire has no tier.
    from sase.bead.attachments.upload import placement_tiers

    tiers = placement_tiers(
        {"public": object()}, git_max_bytes=50 * 1024 * 1024, audience="public"
    )
    assert tiers and tiers[0]["max_bytes"] == cap
    from sase.core.rust import require_rust_binding

    placement = require_rust_binding("attachment_placement")
    try:
        decision = placement(len(data), tiers, False)
    except ValueError:
        decision = {}
    assert not decision.get("store")
    public = GitAttachmentStore(
        clone, "owner/repo (public)", name="public", layout="public"
    )
    assert not public.has(digest)


def test_outbox_drain_routes_by_store_name(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    public_prober,
    remote: Path,
    private_remote: Path,
) -> None:
    from sase.bead.attachments.git_store import GitAttachmentStore
    from sase.bead.attachments.outbox import (
        OutboxEntry,
        drain_outbox,
        enqueue_outbox,
        read_outbox,
    )

    home = _use_home(monkeypatch, tmp_path, "sase-home-a")
    public_clone = _plant_clone(home, remote, "attachments")
    private_clone = _plant_clone(home, private_remote, "attachments-private")
    _clear_fetch_cache()
    public_data = b"public drain bytes"
    private_data = b"private drain bytes"
    public_digest = hashlib.sha256(public_data).hexdigest()
    private_digest = hashlib.sha256(private_data).hexdigest()
    from sase.bead.attachments.store import LocalAttachmentStore

    local = LocalAttachmentStore()
    local.ensure_dirs()
    (tmp_path / "pub.bin").write_bytes(public_data)
    (tmp_path / "priv.bin").write_bytes(private_data)
    import shutil

    for digest, src in (
        (public_digest, tmp_path / "pub.bin"),
        (private_digest, tmp_path / "priv.bin"),
    ):
        dest = local.object_path(digest)
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src, dest)
    enqueue_outbox(
        "test-project",
        [
            OutboxEntry(
                digest=public_digest,
                size_bytes=len(public_data),
                store="public",
                mime_type="text/plain",
            ),
            OutboxEntry(
                digest=private_digest,
                size_bytes=len(private_data),
                store="git",
            ),
        ],
    )
    public = GitAttachmentStore(
        public_clone, "owner/repo (public)", name="public", layout="public"
    )
    private = GitAttachmentStore(private_clone, "owner/repo (private)")
    drained, remaining = drain_outbox("test-project", public)
    assert drained == 1
    assert any(e.digest == private_digest for e in read_outbox("test-project"))
    drained, _ = drain_outbox("test-project", private)
    assert drained == 1
    assert read_outbox("test-project") == []
    assert public.has(public_digest)
    assert private.has(private_digest)
    assert not public.has(private_digest)


def test_missing_public_store_leaves_row_queued(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, public_prober
) -> None:
    from sase.bead.attachments.outbox import (
        OutboxEntry,
        enqueue_outbox,
        read_outbox,
        remove_outbox_digests,
    )

    _use_home(monkeypatch, tmp_path, "sase-home-a")
    digest = "a" * 64
    enqueue_outbox(
        "test-project",
        [OutboxEntry(digest=digest, size_bytes=10, store="public")],
    )
    # No public clone: discovery yields no public store, so the row stays.
    from sase.bead.attachments.upload import discover_public_store

    assert discover_public_store(None) is None
    assert any(e.digest == digest for e in read_outbox("test-project"))
    remove_outbox_digests("test-project", {digest})


def test_old_outbox_row_still_drains_to_private(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, private_remote: Path
) -> None:
    from sase.bead.attachments.git_store import GitAttachmentStore
    from sase.bead.attachments.outbox import drain_outbox, read_outbox
    from sase.core.paths import sase_projects_dir

    home = _use_home(monkeypatch, tmp_path, "sase-home-a")
    clone = _plant_clone(home, private_remote, "attachments-private")
    _clear_fetch_cache()
    data = b"old row bytes"
    digest = hashlib.sha256(data).hexdigest()
    from sase.bead.attachments.store import LocalAttachmentStore
    import shutil

    local = LocalAttachmentStore()
    local.ensure_dirs()
    src = tmp_path / "old.bin"
    src.write_bytes(data)
    dest = local.object_path(digest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(src, dest)
    # Old row with only digest/size_bytes/store: git.
    path = sase_projects_dir() / "test-project" / "attachment-upload-outbox.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    import json

    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "items": [
                    {"digest": digest, "size_bytes": len(data), "store": "git"},
                ],
            }
        ),
        encoding="utf-8",
    )
    private = GitAttachmentStore(clone, "owner/repo (private)")
    drained, _ = drain_outbox("test-project", private)
    assert drained == 1
    assert read_outbox("test-project") == []


def test_fetch_miss_then_hit_is_not_corrupt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    remote: Path,
    private_remote: Path,
) -> None:
    from sase.bead.attachments.fetch import _FetchContext, _ensure_fetched
    from sase.bead.attachments.git_store import GitAttachmentStore
    from sase.bead.attachments.store import LocalAttachmentStore

    home = _use_home(monkeypatch, tmp_path, "sase-home-a")
    public_clone = _plant_clone(home, remote, "attachments")
    private_clone = _plant_clone(home, private_remote, "attachments-private")
    _clear_fetch_cache()
    data = b"private-only bytes for fetch order"
    digest = hashlib.sha256(data).hexdigest()
    src = tmp_path / "fetch.bin"
    src.write_bytes(data)
    private = GitAttachmentStore(private_clone, "owner/repo (private)")
    private.put(digest, src, len(data))
    public = GitAttachmentStore(
        public_clone, "owner/repo (public)", name="public", layout="public"
    )
    assert not public.has(digest)
    context = _FetchContext(
        mode="force", stores=[public, private], outbox={}, cap_bytes=26214400
    )
    assert _ensure_fetched(context, digest, visibility="public")
    assert digest not in context.corrupt
    assert LocalAttachmentStore().verify(digest)


def test_digest_mismatch_still_corrupt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, private_remote: Path
) -> None:
    from sase.bead.attachments.fetch import _FetchContext, _ensure_fetched
    from sase.bead.attachments.git_store import GitAttachmentStore

    home = _use_home(monkeypatch, tmp_path, "sase-home-a")
    clone = _plant_clone(home, private_remote, "attachments-private")
    _clear_fetch_cache()
    data = b"real bytes"
    digest = hashlib.sha256(data).hexdigest()
    src = tmp_path / "real.bin"
    src.write_bytes(data)
    private = GitAttachmentStore(clone, "owner/repo (private)")
    private.put(digest, src, len(data))
    # Tamper the remote object so the digest mismatches.
    import sase_core_rs

    relpath = sase_core_rs.artifact_object_relpath(digest)
    proc = subprocess.run(
        ["git", "hash-object", "-w", "--stdin"],
        cwd=clone,
        input=b"tampered",
        capture_output=True,
        timeout=_GIT_TIMEOUT,
    )
    assert proc.returncode == 0
    blob_id = proc.stdout.decode().strip()
    env = {**_COMMIT_ENV, "GIT_INDEX_FILE": str(clone / "tamper-index")}
    tip = subprocess.run(
        ["git", "rev-parse", "refs/heads/main"],
        cwd=clone,
        check=True,
        capture_output=True,
        text=True,
        timeout=_GIT_TIMEOUT,
    ).stdout.strip()
    subprocess.run(
        ["git", "read-tree", tip],
        cwd=clone,
        check=True,
        env=env,
        capture_output=True,
        timeout=_GIT_TIMEOUT,
    )
    subprocess.run(
        ["git", "update-index", "--cacheinfo", f"100644,{blob_id},{relpath}"],
        cwd=clone,
        check=True,
        env=env,
        capture_output=True,
        timeout=_GIT_TIMEOUT,
    )
    tree = subprocess.run(
        ["git", "write-tree"],
        cwd=clone,
        check=True,
        env=env,
        capture_output=True,
        text=True,
        timeout=_GIT_TIMEOUT,
    ).stdout.strip()
    commit = subprocess.run(
        ["git", "commit-tree", tree, "-p", tip, "-m", "tamper"],
        cwd=clone,
        check=True,
        env=env,
        capture_output=True,
        text=True,
        timeout=_GIT_TIMEOUT,
    ).stdout.strip()
    subprocess.run(
        ["git", "update-ref", "refs/heads/main", commit],
        cwd=clone,
        check=True,
        capture_output=True,
        timeout=_GIT_TIMEOUT,
    )
    _git(clone, "push", "origin", "refs/heads/main:refs/heads/main")
    _clear_fetch_cache()
    # Fresh clone view so the tampered tip is fetched.
    context = _FetchContext(
        mode="force", stores=[private], outbox={}, cap_bytes=26214400
    )
    assert not _ensure_fetched(context, digest, visibility="private")
    assert digest in context.corrupt


def test_ensure_discovered_copies_stores(tmp_path: Path) -> None:
    from sase.bead.attachments.fetch import (
        _FetchContext,
        _ensure_discovered,
        fetch_context,
    )

    with fetch_context(mode="never") as context:
        assert context.discover is True
        _ensure_discovered(context)
        assert context.discover is False
        assert isinstance(context.stores, list)
    assert _FetchContext().stores == []


def test_disabled_role_hidden_even_with_clone(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, remote: Path
) -> None:
    from types import SimpleNamespace

    home = _use_home(monkeypatch, tmp_path, "sase-home-a")
    _plant_clone(home, remote, "attachments")
    _clear_fetch_cache()
    context = SimpleNamespace(project_key="test-project")
    from sase.bead.attachments.upload import discover_public_store

    monkeypatch.setattr(
        "sase.bead.attachments.upload.discovery._sidecar_entry_for_role",
        lambda role: {"role": role},
    )
    assert discover_public_store(context) is not None
    monkeypatch.setattr(
        "sase.bead.attachments.upload.discovery._sidecar_entry_for_role",
        lambda role: {"role": role, "disabled": True},
    )
    assert discover_public_store(context) is None


def test_disabled_private_role_hidden_even_with_clone(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, private_remote: Path
) -> None:
    """A disabled attachments-private role never uploads through its clone."""
    from types import SimpleNamespace

    from sase.bead.attachments.upload import discover_shared_store

    home = _use_home(monkeypatch, tmp_path, "sase-home-a")
    _plant_clone(home, private_remote, "attachments-private")
    context = SimpleNamespace(project_key="test-project")
    monkeypatch.setattr(
        "sase.bead.attachments.upload.discovery._sidecar_entry_for_role",
        lambda role: {"role": role},
    )
    assert discover_shared_store(context) is not None
    monkeypatch.setattr(
        "sase.bead.attachments.upload.discovery._sidecar_entry_for_role",
        lambda role: {"role": role, "disabled": True},
    )
    assert discover_shared_store(context) is None


def test_secret_scan_rejection_blocks_and_narrows(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, remote: Path
) -> None:
    from sase.bead.attachments.git_store.plumbing import _is_secret_scan_rejection
    from sase.bead.attachments.outbox import (
        OutboxEntry,
        enqueue_outbox,
        read_outbox,
    )

    assert _is_secret_scan_rejection("remote: GH013: push declined")
    assert _is_secret_scan_rejection("Push cannot contain secrets")
    assert _is_secret_scan_rejection("push declined due to repository rule violations")
    assert not _is_secret_scan_rejection("non-fast-forward")
    _use_home(monkeypatch, tmp_path, "sase-home-a")
    digest = "b" * 64
    enqueue_outbox(
        "test-project",
        [OutboxEntry(digest=digest, size_bytes=10, store="public")],
    )
    from sase.bead.attachments.outbox import mark_outbox_blocked

    mark_outbox_blocked("test-project", digest, "public")
    rows = read_outbox("test-project")
    assert rows and rows[0].state == "blocked"
    # A blocked row is never resurrected as pending.
    enqueue_outbox(
        "test-project",
        [OutboxEntry(digest=digest, size_bytes=10, store="public")],
    )
    assert read_outbox("test-project")[0].state == "blocked"
    # Blocked rows are not pending_upload.
    from sase.bead.attachments.fetch import _FetchContext, attachment_state

    context = _FetchContext(
        stores=[],
        outbox={digest: read_outbox("test-project")[0]},
    )
    assert attachment_state(digest, context=context) != "pending_upload"
