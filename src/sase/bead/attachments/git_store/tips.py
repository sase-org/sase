"""Cached-tip handling for the git-backed attachment store.

:class:`GitStoreTips` is the tip-handling mixin of
:class:`~sase.bead.attachments.git_store.store.GitAttachmentStore`: branch
resolution, cached local tips, bounded fetches, and the fetch-then-move
rebuild used after a non-fast-forward push. Read and write mixins build
on this class; only public names are imported from other new modules.
"""

from __future__ import annotations

import logging
import subprocess
from pathlib import Path

from sase.bead.attachments.blob_store import BlobStoreError
from sase.bead.attachments.git_store._common import (
    LOCAL_GIT_TIMEOUT_SECONDS,
    run_git,
)
from sase.bead.attachments.git_store.plumbing import update_ref

log = logging.getLogger(__name__)

_DEFAULT_BRANCH = "main"


class GitStoreTips:
    """Branch/tip plumbing shared by the store read and write paths."""

    _repo: Path
    _label: str
    _fetch_timeout: float

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

    def _fetch_now(self, branch: str) -> str | None:
        """Fetch *branch* from origin within the bounded timeout.

        Returns ``None`` on success, else the failure detail (stderr tail or
        the transport exception). Callers surface the detail so readers can
        tell an access denial apart from a plain miss.
        """

        try:
            result = run_git(
                ["fetch", "--quiet", "origin", branch],
                cwd=self._repo,
                timeout=self._fetch_timeout,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            detail = str(exc).strip() or "unknown git error"
            log.warning("attachment git fetch failed for %r: %s", branch, detail)
            return detail
        if result.returncode != 0:
            detail = (result.stderr or result.stdout or "unknown git error").strip()
            log.warning("attachment git fetch failed for %r: %s", branch, detail)
            return detail
        return None

    def _rebase_local_onto_remote(self, branch: str, ref: str) -> None:
        """Fetch and move the local branch to the fetched tip for a rebuild."""

        if (detail := self._fetch_now(branch)) is not None:
            raise BlobStoreError(
                f"cannot reach {self._label}: git fetch failed: {detail[-500:]}",
                transient=True,
            )
        remote_tip = self._fetch_head_tip() or self._cached_tip(branch)
        if remote_tip is None:
            raise BlobStoreError(
                f"git fetch of {self._label} returned no tip for {branch!r}",
                transient=True,
            )
        update_ref(self._repo, ref, remote_tip)
