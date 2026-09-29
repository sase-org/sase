"""Git-backed blob store over a bare partial clone.

:class:`GitAttachmentStore` implements the :class:`BlobStore` protocol over a
bare ``--filter=blob:none`` clone (the ``attachments-private`` sidecar owned
by phase ``sidecar_role``). Tip handling and the :class:`BlobStore` methods
live here; git-tree plumbing lives in :mod:`plumbing` and shared bounds in
the private :mod:`_common` module.
"""

from __future__ import annotations

import contextlib
import fcntl
import hashlib
import logging
import subprocess
import threading
from collections.abc import Iterator
from pathlib import Path

from sase.bead.attachments.blob_store import BlobStoreError, ProgressCallback
from sase.bead.attachments.git_store._common import (
    CHUNK_SIZE,
    LOCAL_GIT_TIMEOUT_SECONDS,
    run_git,
)
from sase.bead.attachments.git_store.plumbing import (
    blob_size,
    build_tree,
    build_tree_without,
    commit_tree,
    stream_blob,
    sync_ref,
    update_ref,
    write_object,
)
from sase.bead.attachments.store import LocalAttachmentStore, validate_sha256
from sase.core.rust import require_rust_binding

log = logging.getLogger(__name__)

_STORE_COMMIT_PREFIX = "chore(attachments): store"
_DELETE_COMMIT_PREFIX = "chore(attachments): delete"
_PUSH_ATTEMPTS = 3
_DEFAULT_BRANCH = "main"

_FETCHED_REPOS: set[str] = set()
_FETCHED_LOCK = threading.Lock()


def _object_relpath(sha256: str) -> str:
    """Return the canonical remote object path for *sha256*.

    The layout comes from ``sase_core_rs.artifact_object_relpath`` and the
    shape is pinned by the prompt-archive quarantine rule
    (:func:`canonical_archive_object_digest`): a bare repo has no worktree
    to quarantine into, so a non-canonical path is an error here.
    """

    relpath = str(require_rust_binding("artifact_object_relpath")(sha256))
    from sase.agents_sync.prompt_archive.archive_objects import (
        canonical_archive_object_digest,
    )

    if canonical_archive_object_digest(relpath) != sha256:
        raise BlobStoreError(
            f"git store path for {sha256[:16]}… is not canonical: {relpath!r}"
        )
    return relpath


def _tombstone_relpath(sha256: str) -> str:
    """Return the canonical remote tombstone path for *sha256*.

    Tombstones live at ``files/tombstones/sha256/<xx>/<sha>.json`` next to
    the content-addressed object layout from
    ``sase_core_rs.artifact_object_relpath``.
    """

    validate_sha256(sha256)
    object_relpath = _object_relpath(sha256)
    prefix = "files/objects/sha256/"
    if not object_relpath.startswith(prefix) or not object_relpath.endswith(sha256):
        raise BlobStoreError(
            f"git store tombstone for {sha256[:16]}… has no canonical path: "
            f"{object_relpath!r}"
        )
    return f"files/tombstones/sha256/{sha256[:2]}/{sha256}.json"


@contextlib.contextmanager
def _writer_lock(repo: Path) -> Iterator[None]:
    """Hold an exclusive lock inside the bare git dir for a whole update."""

    lock_path = repo / "sase-git-store.lock"
    with open(lock_path, "ab") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            with contextlib.suppress(OSError):
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


class GitAttachmentStore:
    """A :class:`BlobStore` over a bare partial clone, written with plumbing."""

    def __init__(
        self,
        repo: Path | str,
        label: str,
        *,
        fetch_timeout: float | None = None,
    ) -> None:
        """Point at the bare repo at *repo*; *label* feeds :meth:`describe`."""

        path = Path(repo).expanduser()
        if (
            not path.is_dir()
            or not (path / "HEAD").is_file()
            or not (path / "objects").is_dir()
        ):
            raise BlobStoreError(f"not a bare git repository: {path}")
        self._repo = path
        self._label = label
        if fetch_timeout is not None:
            self._fetch_timeout = fetch_timeout
        else:  # Same bound as every other SDD network git command.
            from sase.sdd._git import network_git_timeout

            self._fetch_timeout = network_git_timeout()

    @property
    def name(self) -> str:
        """Short stable identifier used in logs, badges, and the outbox."""

        return "git"

    def describe(self) -> str:
        """Human-readable destination/visibility label for the write echo."""

        return self._label

    # -- tip handling -------------------------------------------------

    def _branch(self) -> str:
        """Return the short branch name HEAD points at."""

        result = run_git(
            ["symbolic-ref", "--short", "HEAD"],
            cwd=self._repo,
            timeout=LOCAL_GIT_TIMEOUT_SECONDS,
        )
        if result.returncode != 0:
            return _DEFAULT_BRANCH
        return result.stdout.strip() or _DEFAULT_BRANCH

    def _tip(self, branch: str) -> str | None:
        """Return the cached local tip of *branch*, or None when unborn."""

        result = run_git(
            ["rev-parse", "--verify", "--quiet", f"refs/heads/{branch}"],
            cwd=self._repo,
            timeout=LOCAL_GIT_TIMEOUT_SECONDS,
        )
        if result.returncode != 0:
            return None
        return result.stdout.strip() or None

    def _tracking_tip(self, branch: str) -> str | None:
        """Return the remote-tracking tip of *branch*, if the clone has one."""

        result = run_git(
            ["rev-parse", "--verify", "--quiet", f"refs/remotes/origin/{branch}"],
            cwd=self._repo,
            timeout=LOCAL_GIT_TIMEOUT_SECONDS,
        )
        if result.returncode != 0:
            return None
        return result.stdout.strip() or None

    def _fetch_head_tip(self) -> str | None:
        """Return the tip recorded by the most recent fetch, if any."""

        result = run_git(
            ["rev-parse", "--verify", "--quiet", "FETCH_HEAD"],
            cwd=self._repo,
            timeout=LOCAL_GIT_TIMEOUT_SECONDS,
        )
        if result.returncode != 0:
            return None
        return result.stdout.strip() or None

    def _is_ancestor(self, older: str, newer: str) -> bool:
        """Return whether *older* is an ancestor of *newer*."""

        if older == newer:
            return True
        result = run_git(
            ["merge-base", "--is-ancestor", older, newer],
            cwd=self._repo,
            timeout=LOCAL_GIT_TIMEOUT_SECONDS,
        )
        return result.returncode == 0

    def _cached_tip(self, branch: str) -> str | None:
        """Return the newest locally cached tip for *branch*.

        Bare clones typically carry no fetch refspec, so a fetch advances
        ``FETCH_HEAD`` without moving the local branch, while a put advances
        the local branch without fetching. Each cached tip (local branch,
        ``FETCH_HEAD``, tracking ref) can therefore shadow a newer one, so
        the descendant wins by ancestry. Unrelated tips mean an unpushed
        local commit raced a fetch; the local tip wins because it carries
        our own writes, and a push validates before anything is believed.
        """

        tips: list[str] = []
        for tip in (
            self._tip(branch),
            self._fetch_head_tip(),
            self._tracking_tip(branch),
        ):
            if tip is not None and tip not in tips:
                tips.append(tip)
        if not tips:
            return None
        newest = tips[0]
        for tip in tips[1:]:
            if self._is_ancestor(newest, tip):
                newest = tip
        return newest

    def _tree_of(self, tip: str) -> str | None:
        """Return the tree hash of commit *tip*."""

        result = run_git(
            ["rev-parse", "--verify", "--quiet", f"{tip}^{{tree}}"],
            cwd=self._repo,
            timeout=LOCAL_GIT_TIMEOUT_SECONDS,
        )
        if result.returncode != 0:
            return None
        return result.stdout.strip() or None

    def _entry(self, tip: str, relpath: str) -> str | None:
        """Return the blob id stored at *relpath* in *tip*, if any.

        A ``blob:none`` clone answers this from its (fetched) trees without
        downloading the blob itself.
        """

        result = run_git(
            ["rev-parse", "--verify", "--quiet", f"{tip}:{relpath}"],
            cwd=self._repo,
            timeout=LOCAL_GIT_TIMEOUT_SECONDS,
        )
        if result.returncode != 0:
            return None
        return result.stdout.strip() or None

    def _fetch_now(self, branch: str) -> bool:
        """Fetch *branch* from origin within the bounded timeout."""

        try:
            result = run_git(
                ["fetch", "--quiet", "origin", branch],
                cwd=self._repo,
                timeout=self._fetch_timeout,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            log.warning("attachment git fetch failed for %r: %s", branch, exc)
            return False
        if result.returncode != 0:
            detail = (result.stderr or result.stdout or "unknown git error").strip()
            log.warning("attachment git fetch failed for %r: %s", branch, detail)
            return False
        return True

    def _rebase_local_onto_remote(self, branch: str, ref: str) -> None:
        """Fetch and move the local branch to the fetched tip for a rebuild."""

        if not self._fetch_now(branch):
            raise BlobStoreError(
                f"cannot reach {self._label}: git fetch failed", transient=True
            )
        remote_tip = self._fetch_head_tip() or self._cached_tip(branch)
        if remote_tip is None:
            raise BlobStoreError(
                f"git fetch of {self._label} returned no tip for {branch!r}",
                transient=True,
            )
        update_ref(self._repo, ref, remote_tip)

    # -- BlobStore ----------------------------------------------------

    def has(self, sha256: str) -> bool:
        """Return whether the object for *sha256* is present in this store.

        At most one bounded fetch per process refreshes the cached tip; a
        failed fetch keeps the last cached tip and never raises.
        """

        validate_sha256(sha256)
        relpath = _object_relpath(sha256)
        branch = self._branch()
        key = str(self._repo)
        with _FETCHED_LOCK:
            if key in _FETCHED_REPOS:
                tip = self._cached_tip(branch)
                return tip is not None and self._entry(tip, relpath) is not None
            _FETCHED_REPOS.add(key)
        if self._fetch_now(branch):
            tip = self._fetch_head_tip() or self._cached_tip(branch)
        else:
            tip = self._cached_tip(branch)
        return tip is not None and self._entry(tip, relpath) is not None

    def has_tombstone(self, sha256: str) -> bool:
        """Return whether a purge tombstone for *sha256* is in this store.

        Tombstones live at ``files/tombstones/sha256/<xx>/<sha>.json`` next
        to the ``files/objects/…`` layout. This reads the already-fetched
        tip and never fetches: call :meth:`has` first on paths that need a
        fresh tip. Never raises for git failures; purge stays a later phase.
        """

        validate_sha256(sha256)
        try:
            relpath = _tombstone_relpath(sha256)
            branch = self._branch()
            tip = self._cached_tip(branch) or self._fetch_head_tip()
        except Exception:
            return False
        if tip is None:
            return False
        try:
            return self._entry(tip, relpath) is not None
        except Exception:
            return False

    def put(
        self,
        sha256: str,
        src: Path,
        size_bytes: int,
        progress: ProgressCallback | None = None,
    ) -> None:
        """Upload the local file *src* under digest *sha256*.

        The file's bytes are hashed first and a digest mismatch is refused
        without touching the repo. The update holds an exclusive flock
        inside the bare git dir; on a non-fast-forward push the tip is
        refetched and the content-addressed tree rebuilt (bounded retries).
        A repeated put of the same digest commits nothing and succeeds.
        """

        validate_sha256(sha256)
        source = Path(src)
        if not source.is_file() or source.is_symlink():
            raise BlobStoreError(f"cannot store {source}: not a regular file")
        actual = self._hash_file(source, size_bytes, progress)
        if actual != sha256:
            raise BlobStoreError(
                f"cannot store {source}: bytes hash to {actual[:16]}…, "
                f"not {sha256[:16]}…"
            )
        relpath = _object_relpath(sha256)
        branch = self._branch()
        ref = f"refs/heads/{branch}"
        blob = write_object(self._repo, source, self._fetch_timeout)
        with _writer_lock(self._repo):
            for _attempt in range(_PUSH_ATTEMPTS):
                base = self._cached_tip(branch)
                new_tree = build_tree(self._repo, base, blob, relpath)
                if base is not None and new_tree == self._tree_of(base):
                    if sync_ref(self._repo, ref, self._fetch_timeout):
                        return
                else:
                    parents = [] if base is None else ["-p", base]
                    commit = commit_tree(
                        self._repo,
                        new_tree,
                        parents,
                        f"{_STORE_COMMIT_PREFIX} {sha256}",
                    )
                    update_ref(self._repo, ref, commit)
                    if sync_ref(self._repo, ref, self._fetch_timeout):
                        return
                self._rebase_local_onto_remote(branch, ref)
            raise BlobStoreError(
                f"could not push attachment {sha256[:16]}… to origin "
                f"after {_PUSH_ATTEMPTS} attempts",
                transient=True,
            )

    def get(
        self,
        sha256: str,
        dest: Path,
        progress: ProgressCallback | None = None,
    ) -> None:
        """Download digest *sha256* into the local CAS rooted at *dest*.

        The blob streams from ``git cat-file`` (the promisor fetch) into a
        CAS temp file while its SHA-256 is verified; on mismatch nothing is
        installed and a durable :class:`BlobStoreError` is raised. Success
        installs through the local store replace rules: same filesystem,
        per-digest flock, mode 0444.
        """

        validate_sha256(sha256)
        relpath = _object_relpath(sha256)
        cas = LocalAttachmentStore(root=Path(dest))
        cas.ensure_dirs()
        target = cas.object_path(sha256)
        if target.is_file() and cas.verify(sha256):
            return
        branch = self._branch()
        tip = self._cached_tip(branch)
        blob = self._entry(tip, relpath) if tip is not None else None
        if blob is None:
            key = str(self._repo)
            with _FETCHED_LOCK:
                should_fetch = key not in _FETCHED_REPOS
                if should_fetch:
                    _FETCHED_REPOS.add(key)
            if not should_fetch:
                raise BlobStoreError(
                    f"attachment {sha256[:16]}… is not in {self._label}",
                )
            if not self._fetch_now(branch):
                raise BlobStoreError(
                    f"cannot reach {self._label}: git fetch failed",
                    transient=True,
                )
            tip = self._fetch_head_tip() or self._cached_tip(branch)
            blob = self._entry(tip, relpath) if tip is not None else None
            if blob is None:
                raise BlobStoreError(
                    f"attachment {sha256[:16]}… is not in {self._label}",
                )
        size = blob_size(self._repo, blob, self._fetch_timeout)
        stream_blob(
            self._repo,
            blob,
            sha256,
            cas,
            target,
            size,
            progress,
            self._fetch_timeout,
            self._label,
        )

    def delete(self, sha256: str) -> None:
        """Remove digest *sha256*; a no-op when it is already absent.

        Purge remains a later phase: this only satisfies the protocol and
        writes no tombstone.
        """

        validate_sha256(sha256)
        relpath = _object_relpath(sha256)
        branch = self._branch()
        ref = f"refs/heads/{branch}"
        with _writer_lock(self._repo):
            for _attempt in range(_PUSH_ATTEMPTS):
                base = self._cached_tip(branch)
                if base is None or self._entry(base, relpath) is None:
                    return
                new_tree = build_tree_without(self._repo, base, relpath)
                if new_tree == self._tree_of(base):
                    return
                commit = commit_tree(
                    self._repo,
                    new_tree,
                    ["-p", base],
                    f"{_DELETE_COMMIT_PREFIX} {sha256}",
                )
                update_ref(self._repo, ref, commit)
                if sync_ref(self._repo, ref, self._fetch_timeout):
                    return
                self._rebase_local_onto_remote(branch, ref)
            raise BlobStoreError(
                f"could not push attachment delete of {sha256[:16]}… "
                f"after {_PUSH_ATTEMPTS} attempts",
                transient=True,
            )

    # -- plumbing -----------------------------------------------------

    @staticmethod
    def _hash_file(
        source: Path, size_bytes: int, progress: ProgressCallback | None
    ) -> str:
        """Return the SHA-256 of *source*, reporting read progress."""

        try:
            handle = open(source, "rb")
        except OSError as exc:
            raise BlobStoreError(f"cannot read {source} for git store: {exc}") from exc
        digest = hashlib.sha256()
        done = 0
        with handle:
            while True:
                chunk = handle.read(CHUNK_SIZE)
                if not chunk:
                    break
                digest.update(chunk)
                done += len(chunk)
                if progress is not None:
                    progress(done, size_bytes)
        return digest.hexdigest()
