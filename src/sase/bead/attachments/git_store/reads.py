"""Read path for the git-backed attachment store.

:class:`GitStoreReads` extends
:class:`~sase.bead.attachments.git_store.tips.GitStoreTips` with the
:mod:`BlobStore <sase.bead.attachments.blob_store>` read methods
(:meth:`has`, :meth:`has_tombstone`, :meth:`get`) plus the public-layout
candidate helpers they share with the write path. The once-per-process
fetch cache lives here because only the read path consults it; only
public names are imported from other new modules.
"""

from __future__ import annotations

import threading
from pathlib import Path

from sase.bead.attachments.blob_store import BlobStoreError, ProgressCallback
from sase.bead.attachments.git_store._common import (
    LOCAL_GIT_TIMEOUT_SECONDS,
    object_relpath,
    run_git,
    tombstone_relpath,
)
from sase.bead.attachments.git_store.plumbing import (
    blob_size,
    stream_blob,
)
from sase.bead.attachments.git_store.tips import GitStoreTips
from sase.bead.attachments.store import LocalAttachmentStore, validate_sha256
from sase.core.rust import require_rust_binding

_FETCHED_REPOS: set[str] = set()
_FETCHED_LOCK = threading.Lock()


def _public_object_digest(relpath: str) -> str | None:
    """Return the digest for a public object *relpath*, or None when foreign."""

    try:
        return str(
            require_rust_binding("attachment_object_digest_from_relpath")(relpath)
        )
    except Exception:
        return None


class GitStoreReads(GitStoreTips):
    """BlobStore read methods over the cached tips from :class:`GitStoreTips`."""

    _layout: str

    def _public_candidates(self, tip: str, sha256: str) -> list[str]:
        """Return public object paths under *tip* matching *sha256*."""

        prefix = f"files/objects/sha256/{sha256[:2]}/"
        result = run_git(
            ["ls-tree", "-r", "--name-only", tip, "--", prefix.rstrip("/")],
            cwd=self._repo,
            timeout=LOCAL_GIT_TIMEOUT_SECONDS,
        )
        if result.returncode != 0:
            return []
        matches: list[str] = []
        for line in (result.stdout or "").splitlines():
            name = line.strip()
            if not name.startswith(prefix):
                continue
            if _public_object_digest(name) == sha256:
                matches.append(name)
        return matches

    def _resolve_public_relpath(self, tip: str | None, sha256: str) -> str | None:
        """Return one public object path for *sha256* at *tip*, if any."""

        if tip is None:
            return None
        try:
            candidates = self._public_candidates(tip, sha256)
        except Exception:
            return None
        return candidates[0] if candidates else None

    def _tip_for_read(self, branch: str) -> str | None:
        """Return the best cached tip, fetching once per process."""

        key = str(self._repo)
        with _FETCHED_LOCK:
            if key in _FETCHED_REPOS:
                return self._cached_tip(branch)
            _FETCHED_REPOS.add(key)
        if self._fetch_now(branch) is None:
            return self._fetch_head_tip() or self._cached_tip(branch)
        return self._cached_tip(branch)

    def has(self, sha256: str) -> bool:
        """Return whether the object for *sha256* is present in this store.

        At most one bounded fetch per process refreshes the cached tip; a
        failed fetch keeps the last cached tip and never raises.
        """

        validate_sha256(sha256)
        branch = self._branch()
        if self._layout == "public":
            key = str(self._repo)
            with _FETCHED_LOCK:
                if key in _FETCHED_REPOS:
                    tip = self._cached_tip(branch)
                    return self._resolve_public_relpath(tip, sha256) is not None
                _FETCHED_REPOS.add(key)
            if self._fetch_now(branch) is None:
                tip = self._fetch_head_tip() or self._cached_tip(branch)
            else:
                tip = self._cached_tip(branch)
            return self._resolve_public_relpath(tip, sha256) is not None
        relpath = object_relpath(sha256)
        key = str(self._repo)
        with _FETCHED_LOCK:
            if key in _FETCHED_REPOS:
                tip = self._cached_tip(branch)
                return tip is not None and self._entry(tip, relpath) is not None
            _FETCHED_REPOS.add(key)
        if self._fetch_now(branch) is None:
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
            relpath = tombstone_relpath(sha256)
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
        is_public = self._layout == "public"
        relpath: str = (
            self._resolve_public_relpath(self._cached_tip(self._branch()), sha256) or ""
            if is_public
            else object_relpath(sha256)
        )
        # The public tip may be stale; the fetch below refreshes it when the
        # object is not found at the cached tip.
        cas = LocalAttachmentStore(root=Path(dest))
        cas.ensure_dirs()
        target = cas.object_path(sha256)
        if target.is_file() and cas.verify(sha256):
            return
        branch = self._branch()
        tip = self._cached_tip(branch)
        if is_public:
            relpath = self._resolve_public_relpath(tip, sha256) or ""
            blob = self._entry(tip, relpath) if tip is not None and relpath else None
        else:
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
                    missing=True,
                )
            if (fetch_detail := self._fetch_now(branch)) is not None:
                raise BlobStoreError(
                    f"cannot reach {self._label}: git fetch failed: "
                    f"{fetch_detail[-500:]}",
                    transient=True,
                )
            tip = self._fetch_head_tip() or self._cached_tip(branch)
            if is_public:
                relpath = self._resolve_public_relpath(tip, sha256) or ""
                blob = (
                    self._entry(tip, relpath) if tip is not None and relpath else None
                )
            else:
                blob = self._entry(tip, relpath) if tip is not None else None
            if blob is None:
                raise BlobStoreError(
                    f"attachment {sha256[:16]}… is not in {self._label}",
                    missing=True,
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
