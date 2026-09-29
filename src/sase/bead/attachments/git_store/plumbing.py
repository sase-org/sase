"""Git-tree plumbing for the attachment store.

Public free functions here take explicit *repo* / timeout / label arguments
so the :class:`GitAttachmentStore` in :mod:`store` stays under the line
limit. Private helpers (author env, result check, fsync) are used only
inside this module.
"""

from __future__ import annotations

import contextlib
import fcntl
import hashlib
import logging
import os
import subprocess
import tempfile
import time
from pathlib import Path

from sase.bead.attachments.blob_store import BlobStoreError, ProgressCallback
from sase.bead.attachments.git_store._common import (
    CHUNK_SIZE,
    LOCAL_GIT_TIMEOUT_SECONDS,
    git_env,
    run_git,
)
from sase.bead.attachments.store import LocalAttachmentStore

log = logging.getLogger(__name__)

_COMMIT_AUTHOR_NAME = "sase-attachments"
_COMMIT_AUTHOR_EMAIL = "sase-attachments@localhost"


def _commit_env(extra: dict[str, str]) -> dict[str, str]:
    """Return the git environment for index and commit plumbing."""

    return git_env(
        {
            "GIT_AUTHOR_NAME": _COMMIT_AUTHOR_NAME,
            "GIT_AUTHOR_EMAIL": _COMMIT_AUTHOR_EMAIL,
            "GIT_COMMITTER_NAME": _COMMIT_AUTHOR_NAME,
            "GIT_COMMITTER_EMAIL": _COMMIT_AUTHOR_EMAIL,
            **extra,
        }
    )


def _check(
    result: subprocess.CompletedProcess[str], op: str
) -> subprocess.CompletedProcess[str]:
    """Raise a durable error when local plumbing *result* failed."""

    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "unknown git error").strip()
        raise BlobStoreError(f"git {op} failed for attachment store: {detail}")
    return result


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


def write_object(repo: Path, source: Path, fetch_timeout: float) -> str:
    """Write *source* into the repo; return its (repo-format) blob id."""

    result = run_git(
        ["hash-object", "-w", str(source)],
        cwd=repo,
        timeout=fetch_timeout,
    )
    blob = _check(result, "hash-object").stdout.strip()
    if not blob:
        raise BlobStoreError("git hash-object returned no object id")
    return blob


def build_tree(repo: Path, base: str | None, blob: str, relpath: str) -> str:
    """Return a tree with *relpath* pointing at *blob*, based on *base*."""

    index_fd, index_path = tempfile.mkstemp(prefix="sase-attachment-index-")
    os.close(index_fd)
    try:
        env = _commit_env({"GIT_INDEX_FILE": index_path})
        if base is None:
            _check(
                run_git(
                    ["read-tree", "--empty"],
                    cwd=repo,
                    timeout=LOCAL_GIT_TIMEOUT_SECONDS,
                    env=env,
                ),
                "read-tree",
            )
        else:
            _check(
                run_git(
                    ["read-tree", base],
                    cwd=repo,
                    timeout=LOCAL_GIT_TIMEOUT_SECONDS,
                    env=env,
                ),
                "read-tree",
            )
        _check(
            run_git(
                [
                    "update-index",
                    "--add",
                    "--cacheinfo",
                    f"100644,{blob},{relpath}",
                ],
                cwd=repo,
                timeout=LOCAL_GIT_TIMEOUT_SECONDS,
                env=env,
            ),
            "update-index",
        )
        result = run_git(
            ["write-tree"],
            cwd=repo,
            timeout=LOCAL_GIT_TIMEOUT_SECONDS,
            env=env,
        )
        return _check(result, "write-tree").stdout.strip()
    finally:
        with contextlib.suppress(OSError):
            os.unlink(index_path)


def build_tree_without(repo: Path, base: str, relpath: str) -> str:
    """Return the tree of *base* with *relpath* removed.

    The temp index is rebuilt from ``read-tree --empty`` plus one
    ``--cacheinfo`` per surviving entry: removal flags such as
    ``--force-remove`` stat the worktree file, which a bare repo does
    not have, and ``--index-info`` only upserts without deleting.
    """

    index_fd, index_path = tempfile.mkstemp(prefix="sase-attachment-index-")
    os.close(index_fd)
    try:
        env = _commit_env({"GIT_INDEX_FILE": index_path})
        _check(
            run_git(
                ["read-tree", base],
                cwd=repo,
                timeout=LOCAL_GIT_TIMEOUT_SECONDS,
                env=env,
            ),
            "read-tree",
        )
        listed = _check(
            run_git(
                ["ls-files", "--stage", "-z"],
                cwd=repo,
                timeout=LOCAL_GIT_TIMEOUT_SECONDS,
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
        _check(
            run_git(
                ["read-tree", "--empty"],
                cwd=repo,
                timeout=LOCAL_GIT_TIMEOUT_SECONDS,
                env=env,
            ),
            "read-tree",
        )
        for entry in entries:
            _check(
                run_git(
                    ["update-index", "--add", "--cacheinfo", entry],
                    cwd=repo,
                    timeout=LOCAL_GIT_TIMEOUT_SECONDS,
                    env=env,
                ),
                "update-index",
            )
        result = run_git(
            ["write-tree"],
            cwd=repo,
            timeout=LOCAL_GIT_TIMEOUT_SECONDS,
            env=env,
        )
        return _check(result, "write-tree").stdout.strip()
    finally:
        with contextlib.suppress(OSError):
            os.unlink(index_path)


def commit_tree(repo: Path, tree: str, parents: list[str], message: str) -> str:
    """Commit *tree* and return the new commit id."""

    result = run_git(
        ["commit-tree", tree, "-m", message, *parents],
        cwd=repo,
        timeout=LOCAL_GIT_TIMEOUT_SECONDS,
        env=_commit_env({}),
    )
    commit = _check(result, "commit-tree").stdout.strip()
    if not commit:
        raise BlobStoreError("git commit-tree returned no commit id")
    return commit


def update_ref(repo: Path, ref: str, new: str) -> None:
    """Point *ref* at *new* (forced; the writer lock serializes writers)."""

    _check(
        run_git(
            ["update-ref", ref, new],
            cwd=repo,
            timeout=LOCAL_GIT_TIMEOUT_SECONDS,
        ),
        "update-ref",
    )


def sync_ref(repo: Path, ref: str, fetch_timeout: float) -> bool:
    """Push *ref*; True on success, False on a non-fast-forward retry."""

    result = run_git(
        ["push", "origin", f"{ref}:{ref}"],
        cwd=repo,
        timeout=fetch_timeout,
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


def blob_size(repo: Path, blob: str, fetch_timeout: float) -> int | None:
    """Return the byte size of *blob*, for get progress totals."""

    result = run_git(
        ["cat-file", "-s", blob],
        cwd=repo,
        timeout=fetch_timeout,
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


def stream_blob(
    repo: Path,
    blob: str,
    sha256: str,
    cas: LocalAttachmentStore,
    target: Path,
    size: int | None,
    progress: ProgressCallback | None,
    fetch_timeout: float,
    label: str,
) -> None:
    """Stream ``git cat-file blob`` into the CAS, digest-verified.

    That ``cat-file`` is the promisor fetch. A digest mismatch installs
    nothing and raises a durable error; it is never quarantined anywhere
    because a bare repo has no worktree.
    """

    deadline = time.monotonic() + fetch_timeout
    tmp_fd, tmp_name = tempfile.mkstemp(dir=cas.tmp_dir, prefix="git-fetch-")
    tmp_path = Path(tmp_name)
    try:
        digest = hashlib.sha256()
        done = 0
        proc = subprocess.Popen(
            ["git", "cat-file", "blob", blob],
            cwd=repo,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=git_env(),
        )
        try:
            stdout = proc.stdout
            if stdout is None:  # pragma: no cover - defensive
                raise BlobStoreError("git cat-file produced no output stream")
            while True:
                chunk = stdout.read(CHUNK_SIZE)
                if not chunk:
                    break
                if time.monotonic() > deadline:
                    proc.kill()
                    raise BlobStoreError(
                        f"timed out fetching {sha256[:16]}… from {label}",
                        transient=True,
                    )
                os.write(tmp_fd, chunk)
                digest.update(chunk)
                done += len(chunk)
                if progress is not None:
                    progress(done, size)
            try:
                _, stderr = proc.communicate(timeout=LOCAL_GIT_TIMEOUT_SECONDS)
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
                f"(store {label} holds mismatched bytes)",
            )
        _install_verified(tmp_path, sha256, cas, target)
    finally:
        with contextlib.suppress(OSError):
            os.close(tmp_fd)
        with contextlib.suppress(OSError):
            tmp_path.unlink(missing_ok=True)
