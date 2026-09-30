"""Write path for the git-backed attachment store.

:class:`GitStoreWrites` extends
:class:`~sase.bead.attachments.git_store.reads.GitStoreReads` with the
:mod:`BlobStore <sase.bead.attachments.blob_store>` write methods
(:meth:`put`, :meth:`write_tombstone`, :meth:`delete`, :meth:`withdraw`).
The writer lock, commit-message prefixes, and push-attempt bound live
here because only the write path uses them; only public names are
imported from other new modules.
"""

from __future__ import annotations

import contextlib
import fcntl
import hashlib
import tempfile
from collections.abc import Iterator
from pathlib import Path

from sase.bead.attachments.blob_store import BlobStoreError, ProgressCallback
from sase.bead.attachments.git_store._common import (
    CHUNK_SIZE,
    object_relpath,
    tombstone_relpath,
)
from sase.bead.attachments.git_store.plumbing import (
    build_tree,
    build_tree_with_changes,
    build_tree_without,
    commit_tree,
    sync_ref,
    update_ref,
    write_object,
)
from sase.bead.attachments.git_store.reads import GitStoreReads
from sase.bead.attachments.store import validate_sha256
from sase.core.rust import require_rust_binding

_STORE_COMMIT_PREFIX = "chore(attachments): store"
_DELETE_COMMIT_PREFIX = "chore(attachments): delete"
_WITHDRAW_COMMIT_PREFIX = "chore(attachments): withdraw"
_PUSH_ATTEMPTS = 3


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


def _public_object_relpath(sha256: str, mime_type: str | None) -> str:
    """Return the extension-preserving public object path for *sha256*."""

    validate_sha256(sha256)
    relpath = str(
        require_rust_binding("attachment_public_object_relpath")(sha256, mime_type)
    )
    return relpath


class GitStoreWrites(GitStoreReads):
    """BlobStore write methods over the read mixin's tip resolution."""

    def put(
        self,
        sha256: str,
        src: Path,
        size_bytes: int,
        progress: ProgressCallback | None = None,
        *,
        mime_type: str | None = None,
    ) -> None:
        """Upload the local file *src* under digest *sha256*.

        The file's bytes are hashed first and a digest mismatch is refused
        without touching the repo. The update holds an exclusive flock
        inside the bare git dir; on a non-fast-forward push the tip is
        refetched and the content-addressed tree rebuilt (bounded retries).
        A repeated put of the same digest commits nothing and succeeds.
        The public layout writes the extension-preserving path for
        *mime_type*; the private layout keeps the extensionless path.
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
        if self._layout == "public":
            relpath = _public_object_relpath(sha256, mime_type)
        else:
            relpath = object_relpath(sha256)
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

    def write_tombstone(self, sha256: str, payload: bytes) -> None:
        """Record a purge tombstone for *sha256* and remove its object.

        The tombstone blob is added at
        ``files/tombstones/sha256/<xx>/<sha>.json`` while the object blob
        is removed in the same plumbing commit, so the tip never shows
        bytes without their tombstone. Retries on non-fast-forward push;
        a repeated write commits nothing and succeeds. The commit message
        names the digest only, never filenames.
        """

        from sase.bead.attachments.tombstones import parse_tombstone_bytes

        validate_sha256(sha256)
        if not isinstance(payload, (bytes, bytearray)) or not bytes(payload):
            raise BlobStoreError("cannot write an empty purge tombstone")
        parsed = parse_tombstone_bytes(bytes(payload))
        if parsed["sha256"] != sha256:
            raise BlobStoreError(
                f"purge tombstone is for {parsed['sha256'][:16]}…, not {sha256[:16]}…"
            )
        tombstone_path = tombstone_relpath(sha256)
        branch = self._branch()
        ref = f"refs/heads/{branch}"
        with _writer_lock(self._repo):
            for _attempt in range(_PUSH_ATTEMPTS):
                base = self._cached_tip(branch)
                if self._layout == "public":
                    removals = (
                        self._public_candidates(base, sha256)
                        if base is not None
                        else []
                    )
                    if (
                        base is not None
                        and self._entry(base, tombstone_path) is not None
                        and not removals
                    ):
                        return
                    object_relpaths = removals
                else:
                    object_path = object_relpath(sha256)
                    if (
                        base is not None
                        and self._entry(base, tombstone_path) is not None
                    ):
                        if self._entry(base, object_path) is None:
                            return
                    object_relpaths = [object_path]
                with tempfile.NamedTemporaryFile(
                    prefix="sase-attachment-tombstone-", suffix=".json"
                ) as handle:
                    handle.write(bytes(payload))
                    handle.flush()
                    blob = write_object(
                        self._repo, Path(handle.name), self._fetch_timeout
                    )
                if self._layout == "public":
                    removal_list = list(object_relpaths)
                    if base is None:
                        # No base: tombstone only; object cannot exist.
                        removal_list = []
                else:
                    removal_list = list(object_relpaths)
                new_tree = build_tree_with_changes(
                    self._repo,
                    base,
                    {tombstone_path: blob},
                    removal_list,
                )
                if base is not None and new_tree == self._tree_of(base):
                    if sync_ref(self._repo, ref, self._fetch_timeout):
                        return
                else:
                    parents = [] if base is None else ["-p", base]
                    commit = commit_tree(
                        self._repo,
                        new_tree,
                        parents,
                        f"chore(attachments): purge {sha256}",
                    )
                    update_ref(self._repo, ref, commit)
                    if sync_ref(self._repo, ref, self._fetch_timeout):
                        return
                self._rebase_local_onto_remote(branch, ref)
            raise BlobStoreError(
                f"could not push attachment purge of {sha256[:16]}… "
                f"after {_PUSH_ATTEMPTS} attempts",
                transient=True,
            )

    def delete(self, sha256: str) -> None:
        """Remove digest *sha256*; a no-op when it is already absent.

        This only satisfies the protocol and writes no tombstone; purge
        flows use :meth:`write_tombstone` instead.
        """

        validate_sha256(sha256)
        branch = self._branch()
        ref = f"refs/heads/{branch}"
        with _writer_lock(self._repo):
            for _attempt in range(_PUSH_ATTEMPTS):
                base = self._cached_tip(branch)
                if base is None:
                    return
                if self._layout == "public":
                    candidates = self._public_candidates(base, sha256)
                    if not candidates:
                        return
                    relpath = candidates[0]
                else:
                    relpath = object_relpath(sha256)
                if self._entry(base, relpath) is None:
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

    def withdraw(self, sha256: str) -> None:
        """Remove digest *sha256* from the public tree without a tombstone.

        Unpublish narrows the descriptor to private while the private copy
        stays readable, so unlike purge this writes no tombstone that would
        hide the private copy. A no-op when the object is already absent.
        """

        validate_sha256(sha256)
        branch = self._branch()
        ref = f"refs/heads/{branch}"
        with _writer_lock(self._repo):
            for _attempt in range(_PUSH_ATTEMPTS):
                base = self._cached_tip(branch)
                if base is None:
                    return
                if self._layout == "public":
                    candidates = self._public_candidates(base, sha256)
                    if not candidates:
                        return
                    relpath = candidates[0]
                else:
                    relpath = object_relpath(sha256)
                if self._entry(base, relpath) is None:
                    return
                new_tree = build_tree_without(self._repo, base, relpath)
                if new_tree == self._tree_of(base):
                    return
                commit = commit_tree(
                    self._repo,
                    new_tree,
                    ["-p", base],
                    f"{_WITHDRAW_COMMIT_PREFIX} {sha256}",
                )
                update_ref(self._repo, ref, commit)
                if sync_ref(self._repo, ref, self._fetch_timeout):
                    return
                self._rebase_local_onto_remote(branch, ref)
            raise BlobStoreError(
                f"could not push attachment withdraw of {sha256[:16]}… "
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
