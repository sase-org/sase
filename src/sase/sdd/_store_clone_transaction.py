"""Atomic staging transactions for SDD Git clone materialization."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
import fcntl
import hashlib
import json
import os
from pathlib import Path
import shutil
import time
import uuid

from sase.sdd._store_git import same_git_remote as _same_git_remote

CLONE_STAGE_CONTAINER_NAME = ".sase-sdd-clone-staging"
CLONE_TARGET_LOCK_POLL_SECONDS = 0.1
CLONE_VALIDATION_TIMEOUT_SECONDS = 30.0
_CLONE_STAGE_METADATA = "owner.json"


class ClonePublicationError(RuntimeError):
    """Raised when a staged clone cannot be safely published."""


class CloneTransactionTimeout(RuntimeError):
    """Raised when the target materialization lock cannot be acquired in time."""


class _CloneMaterializationTransaction:
    def __init__(self, target: Path, *, deadline: float | None) -> None:
        self.target = target.expanduser()
        self.stage_container = self.target.parent / CLONE_STAGE_CONTAINER_NAME
        self._target_key = _clone_target_key(self.target)
        self._entry_prefix = (
            f"{_safe_stage_component(self.target.name)}-{self._target_key[:16]}"
        )
        self.entry_path = (
            self.stage_container / f"{self._entry_prefix}-{uuid.uuid4().hex}"
        )
        self.clone_path = self.entry_path / "clone"
        self._lock_path = self.stage_container / f"{self._entry_prefix}.lock"
        self._lock_fd = -1
        self._deadline = deadline

    def __enter__(self) -> _CloneMaterializationTransaction:
        self.target.parent.mkdir(parents=True, exist_ok=True)
        self.stage_container.mkdir(parents=True, exist_ok=True)
        self._lock_fd = _acquire_clone_target_lock(
            self._lock_path,
            self.target,
            deadline=self._deadline,
        )
        self._reap_abandoned_target_stages()
        self.entry_path.mkdir(mode=0o700)
        _write_clone_stage_metadata(
            self.entry_path,
            target=self.target,
            target_key=self._target_key,
        )
        return self

    def __exit__(
        self,
        exc_type: object,
        exc: object,
        traceback: object,
    ) -> None:
        self.discard_stage()
        if self._lock_fd >= 0:
            try:
                fcntl.flock(self._lock_fd, fcntl.LOCK_UN)
            finally:
                os.close(self._lock_fd)
                self._lock_fd = -1

    def discard_stage(self) -> None:
        _remove_clone_stage_path(self.entry_path)

    def publish(self, *, expected_remote: str | None, deadline: float | None) -> None:
        validate_staged_sdd_clone(
            self.clone_path,
            expected_remote=expected_remote,
            deadline=deadline,
        )
        if os.path.lexists(self.target):
            if valid_published_sdd_clone(
                self.target,
                expected_remote=expected_remote,
                deadline=deadline,
            ):
                self.discard_stage()
                return
            raise ClonePublicationError(
                f"refusing to overwrite existing SDD store at {self.target}; "
                "the concurrently materialized destination is not a healthy "
                "clone of the configured remote"
            )
        try:
            self.clone_path.replace(self.target)
        except Exception as exc:
            raise ClonePublicationError(
                f"failed to publish staged SDD clone {self.clone_path} to "
                f"{self.target}: {str(exc) or type(exc).__name__}"
            ) from exc

    def _reap_abandoned_target_stages(self) -> None:
        for entry in self.stage_container.iterdir():
            if entry == self.entry_path or not entry.name.startswith(
                f"{self._entry_prefix}-"
            ):
                continue
            if not _stage_entry_belongs_to_target(entry, self._target_key):
                continue
            _remove_clone_stage_path(entry)


@contextmanager
def clone_materialization_transaction(
    target: Path, *, deadline: float | None
) -> Iterator[_CloneMaterializationTransaction]:
    transaction = _CloneMaterializationTransaction(target, deadline=deadline)
    with transaction:
        yield transaction


def _remove_clone_stage_path(path: Path) -> None:
    if path.is_dir() and not path.is_symlink():
        shutil.rmtree(path, ignore_errors=True)
        return
    try:
        path.unlink(missing_ok=True)
    except OSError:
        pass


def valid_published_sdd_clone(
    path: Path, *, expected_remote: str | None, deadline: float | None
) -> bool:
    try:
        validate_staged_sdd_clone(
            path,
            expected_remote=expected_remote,
            deadline=deadline,
        )
    except ClonePublicationError:
        return False
    return True


def validate_staged_sdd_clone(
    path: Path, *, expected_remote: str | None, deadline: float | None
) -> None:
    if not (path / ".git").is_dir():
        raise ClonePublicationError(f"staged SDD clone at {path} has no .git directory")
    branch = _git_validation_stdout(
        path,
        ["symbolic-ref", "--quiet", "--short", "HEAD"],
        op="sdd.clone.validate_branch",
        deadline=deadline,
    )
    if branch is None:
        raise ClonePublicationError(
            f"staged SDD clone at {path} is not on an attached branch"
        )
    head = _git_validation_stdout(
        path,
        ["rev-parse", "--verify", "HEAD"],
        op="sdd.clone.validate_head",
        deadline=deadline,
    )
    # `git clone` of an empty remote leaves an unborn branch with tracking
    # config and no HEAD commit. Sidecar init clones newly created remotes
    # in that state before seeding the first commit.
    if head is None and not _is_unborn_tracked_clone(path, branch, deadline=deadline):
        raise ClonePublicationError(
            f"staged SDD clone at {path} does not have a resolvable HEAD"
        )
    if expected_remote is not None:
        remote = _git_validation_stdout(
            path,
            ["remote", "get-url", "origin"],
            op="sdd.clone.validate_origin",
            deadline=deadline,
        )
        if remote is None or not _same_git_remote(remote, expected_remote):
            raise ClonePublicationError(
                f"staged SDD clone at {path} has origin {remote!r}, expected "
                f"{expected_remote!r}"
            )
    if head is None:
        return
    upstream = _git_validation_stdout(
        path,
        ["rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{upstream}"],
        op="sdd.clone.validate_upstream",
        deadline=deadline,
    )
    if upstream is None:
        raise ClonePublicationError(
            f"staged SDD clone at {path} has no tracking upstream"
        )


def _is_unborn_tracked_clone(
    path: Path, branch: str, *, deadline: float | None
) -> bool:
    if _git_validation_stdout(
        path,
        ["rev-list", "--max-count=1", "--all"],
        op="sdd.clone.validate_empty",
        deadline=deadline,
    ):
        return False
    remote = _git_validation_stdout(
        path,
        ["config", "--get", f"branch.{branch}.remote"],
        op="sdd.clone.validate_unborn_remote",
        deadline=deadline,
    )
    merge = _git_validation_stdout(
        path,
        ["config", "--get", f"branch.{branch}.merge"],
        op="sdd.clone.validate_unborn_merge",
        deadline=deadline,
    )
    return bool(remote) and bool(merge)


def _clone_target_key(target: Path) -> str:
    canonical = str(target.expanduser().resolve(strict=False))
    return hashlib.sha256(canonical.encode("utf-8", "surrogateescape")).hexdigest()


def _safe_stage_component(value: str) -> str:
    safe = "".join(
        char if char.isalnum() or char in {"-", "_", "."} else "_" for char in value
    ).strip(".")
    return safe or "sdd"


def _write_clone_stage_metadata(
    entry_path: Path, *, target: Path, target_key: str
) -> None:
    metadata = {
        "target": str(target.expanduser().resolve(strict=False)),
        "target_key": target_key,
        "pid": os.getpid(),
        "created_at": time.time(),
    }
    (entry_path / _CLONE_STAGE_METADATA).write_text(
        json.dumps(metadata, sort_keys=True),
        encoding="utf-8",
    )


def _stage_entry_belongs_to_target(entry_path: Path, target_key: str) -> bool:
    metadata_path = entry_path / _CLONE_STAGE_METADATA
    if not metadata_path.is_file():
        return True
    try:
        raw = json.loads(metadata_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    return isinstance(raw, dict) and raw.get("target_key") == target_key


def _acquire_clone_target_lock(
    lock_path: Path,
    target: Path,
    *,
    deadline: float | None,
) -> int:
    while True:
        fd = os.open(lock_path, os.O_RDWR | os.O_CREAT, 0o600)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            os.close(fd)
        except OSError:
            os.close(fd)
            raise
        else:
            os.ftruncate(fd, 0)
            os.write(
                fd,
                (
                    f"pid={os.getpid()} target={target} acquired_at={time.time():.6f}\n"
                ).encode(),
            )
            return fd

        if deadline is not None and time.monotonic() >= deadline:
            raise CloneTransactionTimeout(
                f"timed out waiting for SDD clone materialization lock for {target}"
            )
        wait = CLONE_TARGET_LOCK_POLL_SECONDS
        if deadline is not None:
            wait = min(wait, max(0.0, deadline - time.monotonic()))
            if wait <= 0.0:
                raise CloneTransactionTimeout(
                    f"timed out waiting for SDD clone materialization lock for {target}"
                )
        time.sleep(wait)


def _git_validation_stdout(
    path: Path,
    args: list[str],
    *,
    op: str,
    deadline: float | None,
) -> str | None:
    from sase.sdd._git import SddGitCommandTimeout, run_sdd_git

    try:
        timeout = _deadline_timeout(CLONE_VALIDATION_TIMEOUT_SECONDS, deadline)
        if timeout <= 0.0:
            return None
        result = run_sdd_git(
            args,
            cwd=path,
            op=op,
            timeout=timeout,
            check=False,
            capture_output=True,
            text=True,
        )
    except (OSError, SddGitCommandTimeout):
        return None
    if result.returncode != 0:
        return None
    value = result.stdout.strip()
    return value or None


def _deadline_timeout(default: float, deadline: float | None) -> float:
    if deadline is None:
        return max(0.0, default)
    return min(max(0.0, default), max(0.0, deadline - time.monotonic()))
