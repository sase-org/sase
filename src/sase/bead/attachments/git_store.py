"""Git-backed blob store over a bare partial clone.

:class:`GitAttachmentStore` implements the :class:`BlobStore` protocol over a
bare ``--filter=blob:none`` clone (the ``attachments-private`` sidecar owned
by phase ``sidecar_role``). Objects live at the shared content-addressed
layout ``files/objects/sha256/<xx>/<sha256>`` resolved through
``sase_core_rs.artifact_object_relpath``, so concurrent writers storing
different digests never conflict: the loser of a push race fetches the new
tip and rebuilds on it.

The store never touches projects or config: the caller supplies the bare
repo path plus the human-readable ``describe()`` label. Discovery of the
hidden clone is phase ``upload``'s job, using the role constant from phase
``sidecar_role``.
"""

from __future__ import annotations

import contextlib
import fcntl
import hashlib
import logging
import os
import subprocess
import tempfile
import threading
import time
from collections.abc import Iterator
from pathlib import Path

from sase.bead.attachments.blob_store import BlobStoreError, ProgressCallback
from sase.bead.attachments.store import LocalAttachmentStore, validate_sha256
from sase.core.rust import require_rust_binding

log = logging.getLogger(__name__)

_STORE_COMMIT_PREFIX = "chore(attachments): store"
_DELETE_COMMIT_PREFIX = "chore(attachments): delete"
_PUSH_ATTEMPTS = 3
_CHUNK_SIZE = 1 << 20
_COMMIT_AUTHOR_NAME = "sase-attachments"
_COMMIT_AUTHOR_EMAIL = "sase-attachments@localhost"
_DEFAULT_BRANCH = "main"

# Mirrors sase.sdd._git.DEFAULT_LOCAL_GIT_TIMEOUT_SECONDS for plumbing that
# never touches the network. Network transfers use the SDD network timeout
# resolved in __init__ (imported lazily so importing this module stays cheap
# on paths that never touch a store).
_LOCAL_GIT_TIMEOUT_SECONDS = 30.0

_FETCHED_REPOS: set[str] = set()
_FETCHED_LOCK = threading.Lock()


def _git_env(extra: dict[str, str] | None = None) -> dict[str, str]:
    """Return a noninteractive git environment plus *extra* overrides."""

    env = dict(os.environ)
    env["GIT_TERMINAL_PROMPT"] = "0"
    ssh_command = env.get("GIT_SSH_COMMAND", "ssh")
    if "BatchMode=" not in ssh_command:
        ssh_command = f"{ssh_command} -o BatchMode=yes"
    env["GIT_SSH_COMMAND"] = ssh_command
    if extra:
        env.update(extra)
    return env


def _run_git(
    args: list[str],
    *,
    cwd: Path,
    timeout: float,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    """Run one bounded git command, capturing output as text."""

    return subprocess.run(
        ["git", *args],
        cwd=cwd,
        timeout=timeout,
        check=False,
        capture_output=True,
        text=True,
        env=_git_env(env),
    )


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


def _fsync_dir(path: Path) -> None:
    """Fsync a directory so a fresh rename survives a crash."""

    try:
        fd = os.open(path, os.O_RDONLY)
    except OSError:
        return
    try:
        with contextlib.suppress(OSError):
            os.fsync(fd)
    finally:
        os.close(fd)


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

        result = _run_git(
            ["symbolic-ref", "--short", "HEAD"],
            cwd=self._repo,
            timeout=_LOCAL_GIT_TIMEOUT_SECONDS,
        )
        if result.returncode != 0:
            return _DEFAULT_BRANCH
        return result.stdout.strip() or _DEFAULT_BRANCH

    def _tip(self, branch: str) -> str | None:
        """Return the cached local tip of *branch*, or None when unborn."""

        result = _run_git(
            ["rev-parse", "--verify", "--quiet", f"refs/heads/{branch}"],
            cwd=self._repo,
            timeout=_LOCAL_GIT_TIMEOUT_SECONDS,
        )
        if result.returncode != 0:
            return None
        return result.stdout.strip() or None

    def _tracking_tip(self, branch: str) -> str | None:
        """Return the remote-tracking tip of *branch*, if the clone has one."""

        result = _run_git(
            ["rev-parse", "--verify", "--quiet", f"refs/remotes/origin/{branch}"],
            cwd=self._repo,
            timeout=_LOCAL_GIT_TIMEOUT_SECONDS,
        )
        if result.returncode != 0:
            return None
        return result.stdout.strip() or None

    def _fetch_head_tip(self) -> str | None:
        """Return the tip recorded by the most recent fetch, if any."""

        result = _run_git(
            ["rev-parse", "--verify", "--quiet", "FETCH_HEAD"],
            cwd=self._repo,
            timeout=_LOCAL_GIT_TIMEOUT_SECONDS,
        )
        if result.returncode != 0:
            return None
        return result.stdout.strip() or None

    def _is_ancestor(self, older: str, newer: str) -> bool:
        """Return whether *older* is an ancestor of *newer*."""

        if older == newer:
            return True
        result = _run_git(
            ["merge-base", "--is-ancestor", older, newer],
            cwd=self._repo,
            timeout=_LOCAL_GIT_TIMEOUT_SECONDS,
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

    @staticmethod
    def _check(
        result: subprocess.CompletedProcess[str], op: str
    ) -> subprocess.CompletedProcess[str]:
        """Raise a durable error when local plumbing *result* failed."""

        if result.returncode != 0:
            detail = (result.stderr or result.stdout or "unknown git error").strip()
            raise BlobStoreError(f"git {op} failed for attachment store: {detail}")
        return result

    def _tree_of(self, tip: str) -> str | None:
        """Return the tree hash of commit *tip*."""

        result = _run_git(
            ["rev-parse", "--verify", "--quiet", f"{tip}^{{tree}}"],
            cwd=self._repo,
            timeout=_LOCAL_GIT_TIMEOUT_SECONDS,
        )
        if result.returncode != 0:
            return None
        return result.stdout.strip() or None

    def _entry(self, tip: str, relpath: str) -> str | None:
        """Return the blob id stored at *relpath* in *tip*, if any.

        A ``blob:none`` clone answers this from its (fetched) trees without
        downloading the blob itself.
        """

        result = _run_git(
            ["rev-parse", "--verify", "--quiet", f"{tip}:{relpath}"],
            cwd=self._repo,
            timeout=_LOCAL_GIT_TIMEOUT_SECONDS,
        )
        if result.returncode != 0:
            return None
        return result.stdout.strip() or None

    def _fetch_now(self, branch: str) -> bool:
        """Fetch *branch* from origin within the bounded timeout."""

        try:
            result = _run_git(
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
        blob = self._write_object(source)
        with _writer_lock(self._repo):
            for _attempt in range(_PUSH_ATTEMPTS):
                base = self._cached_tip(branch)
                new_tree = self._build_tree(base, blob, relpath)
                if base is not None and new_tree == self._tree_of(base):
                    if self._sync_ref(ref, branch):
                        return
                else:
                    parents = [] if base is None else ["-p", base]
                    commit = self._commit_tree(
                        new_tree, parents, f"{_STORE_COMMIT_PREFIX} {sha256}"
                    )
                    self._update_ref(ref, commit)
                    if self._sync_ref(ref, branch):
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
        size = self._blob_size(blob)
        self._stream_blob(blob, sha256, cas, target, size, progress)

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
                new_tree = self._build_tree_without(base, relpath)
                if new_tree == self._tree_of(base):
                    return
                commit = self._commit_tree(
                    new_tree, ["-p", base], f"{_DELETE_COMMIT_PREFIX} {sha256}"
                )
                self._update_ref(ref, commit)
                if self._sync_ref(ref, branch):
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
                chunk = handle.read(_CHUNK_SIZE)
                if not chunk:
                    break
                digest.update(chunk)
                done += len(chunk)
                if progress is not None:
                    progress(done, size_bytes)
        return digest.hexdigest()

    def _commit_env(self, extra: dict[str, str]) -> dict[str, str]:
        """Return the git environment for index and commit plumbing."""

        return _git_env(
            {
                "GIT_AUTHOR_NAME": _COMMIT_AUTHOR_NAME,
                "GIT_AUTHOR_EMAIL": _COMMIT_AUTHOR_EMAIL,
                "GIT_COMMITTER_NAME": _COMMIT_AUTHOR_NAME,
                "GIT_COMMITTER_EMAIL": _COMMIT_AUTHOR_EMAIL,
                **extra,
            }
        )

    def _write_object(self, source: Path) -> str:
        """Write *source* into the repo; return its (repo-format) blob id."""

        result = _run_git(
            ["hash-object", "-w", str(source)],
            cwd=self._repo,
            timeout=self._fetch_timeout,
        )
        blob = self._check(result, "hash-object").stdout.strip()
        if not blob:
            raise BlobStoreError("git hash-object returned no object id")
        return blob

    def _build_tree(self, base: str | None, blob: str, relpath: str) -> str:
        """Return a tree with *relpath* pointing at *blob*, based on *base*."""

        index_fd, index_path = tempfile.mkstemp(prefix="sase-attachment-index-")
        os.close(index_fd)
        try:
            env = self._commit_env({"GIT_INDEX_FILE": index_path})
            if base is None:
                self._check(
                    _run_git(
                        ["read-tree", "--empty"],
                        cwd=self._repo,
                        timeout=_LOCAL_GIT_TIMEOUT_SECONDS,
                        env=env,
                    ),
                    "read-tree",
                )
            else:
                self._check(
                    _run_git(
                        ["read-tree", base],
                        cwd=self._repo,
                        timeout=_LOCAL_GIT_TIMEOUT_SECONDS,
                        env=env,
                    ),
                    "read-tree",
                )
            self._check(
                _run_git(
                    [
                        "update-index",
                        "--add",
                        "--cacheinfo",
                        f"100644,{blob},{relpath}",
                    ],
                    cwd=self._repo,
                    timeout=_LOCAL_GIT_TIMEOUT_SECONDS,
                    env=env,
                ),
                "update-index",
            )
            result = _run_git(
                ["write-tree"],
                cwd=self._repo,
                timeout=_LOCAL_GIT_TIMEOUT_SECONDS,
                env=env,
            )
            return self._check(result, "write-tree").stdout.strip()
        finally:
            with contextlib.suppress(OSError):
                os.unlink(index_path)

    def _build_tree_without(self, base: str, relpath: str) -> str:
        """Return the tree of *base* with *relpath* removed.

        The temp index is rebuilt from ``read-tree --empty`` plus one
        ``--cacheinfo`` per surviving entry: removal flags such as
        ``--force-remove`` stat the worktree file, which a bare repo does
        not have, and ``--index-info`` only upserts without deleting.
        """

        index_fd, index_path = tempfile.mkstemp(prefix="sase-attachment-index-")
        os.close(index_fd)
        try:
            env = self._commit_env({"GIT_INDEX_FILE": index_path})
            self._check(
                _run_git(
                    ["read-tree", base],
                    cwd=self._repo,
                    timeout=_LOCAL_GIT_TIMEOUT_SECONDS,
                    env=env,
                ),
                "read-tree",
            )
            listed = self._check(
                _run_git(
                    ["ls-files", "--stage", "-z"],
                    cwd=self._repo,
                    timeout=_LOCAL_GIT_TIMEOUT_SECONDS,
                    env=env,
                ),
                "ls-files",
            )
            entries = []
            for record in listed.stdout.split("\0"):
                if not record:
                    continue
                meta, _, path = record.partition("\t")
                if path == relpath:
                    continue
                mode, _, remainder = meta.partition(" ")
                blob, _, _stage = remainder.partition(" ")
                entries.append(f"{mode},{blob},{path}")
            self._check(
                _run_git(
                    ["read-tree", "--empty"],
                    cwd=self._repo,
                    timeout=_LOCAL_GIT_TIMEOUT_SECONDS,
                    env=env,
                ),
                "read-tree",
            )
            for entry in entries:
                self._check(
                    _run_git(
                        ["update-index", "--add", "--cacheinfo", entry],
                        cwd=self._repo,
                        timeout=_LOCAL_GIT_TIMEOUT_SECONDS,
                        env=env,
                    ),
                    "update-index",
                )
            result = _run_git(
                ["write-tree"],
                cwd=self._repo,
                timeout=_LOCAL_GIT_TIMEOUT_SECONDS,
                env=env,
            )
            return self._check(result, "write-tree").stdout.strip()
        finally:
            with contextlib.suppress(OSError):
                os.unlink(index_path)

    def _commit_tree(self, tree: str, parents: list[str], message: str) -> str:
        """Commit *tree* and return the new commit id."""

        result = _run_git(
            ["commit-tree", tree, "-m", message, *parents],
            cwd=self._repo,
            timeout=_LOCAL_GIT_TIMEOUT_SECONDS,
            env=self._commit_env({}),
        )
        commit = self._check(result, "commit-tree").stdout.strip()
        if not commit:
            raise BlobStoreError("git commit-tree returned no commit id")
        return commit

    def _update_ref(self, ref: str, new: str) -> None:
        """Point *ref* at *new* (forced; the writer lock serializes writers)."""

        self._check(
            _run_git(
                ["update-ref", ref, new],
                cwd=self._repo,
                timeout=_LOCAL_GIT_TIMEOUT_SECONDS,
            ),
            "update-ref",
        )

    def _sync_ref(self, ref: str, branch: str) -> bool:
        """Push *ref*; True on success, False on a non-fast-forward retry."""

        result = _run_git(
            ["push", "origin", f"{ref}:{ref}"],
            cwd=self._repo,
            timeout=self._fetch_timeout,
        )
        if result.returncode == 0:
            return True
        detail = (result.stderr or result.stdout or "unknown git error").strip()
        if (
            "non-fast-forward" in detail
            or "fetch first" in detail
            or "[rejected]" in detail
            # A racing writer's push holds the remote ref lock; refetch and
            # rebuild instead of failing the push.
            or "cannot lock ref" in detail
        ):
            log.info("attachment git push needs retry: %s", detail[-300:])
            return False
        raise BlobStoreError(
            f"git push of attachment store failed: {detail[-500:]}",
            transient=True,
        )

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
        self._update_ref(ref, remote_tip)

    def _blob_size(self, blob: str) -> int | None:
        """Return the byte size of *blob*, for get progress totals."""

        result = _run_git(
            ["cat-file", "-s", blob],
            cwd=self._repo,
            timeout=self._fetch_timeout,
        )
        if result.returncode != 0:
            detail = (result.stderr or result.stdout or "unknown git error").strip()
            raise BlobStoreError(
                f"cannot size attachment blob {blob[:16]}…: {detail}",
                transient=True,
            )
        try:
            return int(result.stdout.strip())
        except ValueError:
            return None

    def _stream_blob(
        self,
        blob: str,
        sha256: str,
        cas: LocalAttachmentStore,
        target: Path,
        size: int | None,
        progress: ProgressCallback | None,
    ) -> None:
        """Stream ``git cat-file blob`` into the CAS, digest-verified.

        That ``cat-file`` is the promisor fetch. A digest mismatch installs
        nothing and raises a durable error; it is never quarantined anywhere
        because a bare repo has no worktree.
        """

        deadline = time.monotonic() + self._fetch_timeout
        tmp_fd, tmp_name = tempfile.mkstemp(dir=cas.tmp_dir, prefix="git-fetch-")
        tmp_path = Path(tmp_name)
        try:
            digest = hashlib.sha256()
            done = 0
            proc = subprocess.Popen(
                ["git", "cat-file", "blob", blob],
                cwd=self._repo,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=_git_env(),
            )
            try:
                stdout = proc.stdout
                if stdout is None:  # pragma: no cover - defensive
                    raise BlobStoreError("git cat-file produced no output stream")
                while True:
                    chunk = stdout.read(_CHUNK_SIZE)
                    if not chunk:
                        break
                    if time.monotonic() > deadline:
                        proc.kill()
                        raise BlobStoreError(
                            f"timed out fetching {sha256[:16]}… from {self._label}",
                            transient=True,
                        )
                    os.write(tmp_fd, chunk)
                    digest.update(chunk)
                    done += len(chunk)
                    if progress is not None:
                        progress(done, size)
                try:
                    _, stderr = proc.communicate(timeout=_LOCAL_GIT_TIMEOUT_SECONDS)
                except subprocess.TimeoutExpired as exc:
                    proc.kill()
                    raise BlobStoreError(
                        f"timed out finishing fetch of {sha256[:16]}…",
                        transient=True,
                    ) from exc
                if proc.returncode != 0:
                    detail = (stderr or b"").decode("utf-8", "replace").strip()
                    raise BlobStoreError(
                        f"git cat-file failed for {sha256[:16]}…: {detail}",
                        transient=True,
                    )
            finally:
                with contextlib.suppress(OSError):
                    proc.kill()
                    proc.wait()
            os.fsync(tmp_fd)
            os.close(tmp_fd)
            if digest.hexdigest() != sha256:
                raise BlobStoreError(
                    f"attachment {sha256[:16]}… failed digest verification "
                    f"(store {self._label} holds mismatched bytes)",
                )
            self._install_verified(tmp_path, sha256, cas, target)
        finally:
            with contextlib.suppress(OSError):
                os.close(tmp_fd)
            with contextlib.suppress(OSError):
                tmp_path.unlink(missing_ok=True)

    @staticmethod
    def _install_verified(
        tmp_path: Path, sha256: str, cas: LocalAttachmentStore, target: Path
    ) -> None:
        """Install verified *tmp_path* at *target*: flock, replace, 0444."""

        cas.locks_dir.mkdir(parents=True, exist_ok=True)
        lock_path = cas.locks_dir / f"{sha256}.lock"
        with open(lock_path, "ab") as handle:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            try:
                if target.is_file() and cas.verify(sha256):
                    return
                target.parent.mkdir(parents=True, exist_ok=True)
                os.replace(tmp_path, target)
                os.chmod(target, 0o444)
                _fsync_dir(target.parent)
            finally:
                with contextlib.suppress(OSError):
                    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
