"""Private staging and scanner adapter for agents publication."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
import hashlib
import os
from pathlib import Path
import shutil
import stat
import tempfile

from sase._interruptions import PublicationDrainTimedOut
from sase.agents_sync._publication_protection_models import (
    PRIVATE_SCAN_STAGING_DIRECTORY,
    PublicationBytesVerdict,
)
from sase.core.agent_publication_protection import publication_scan_disposition
from sase.core.paths import sase_home


@dataclass(frozen=True, slots=True)
class ScannedPublicationCandidate:
    """One private candidate copy and its scan decision.

    Keep this object inside ``_scan_publication_candidate``'s context. A
    publisher may only copy the private staged bytes after a clean scan.
    """

    staged_path: Path | None
    sha256: str | None
    byte_count: int | None
    disposition: dict[str, object] | None

    @property
    def is_publishable(self) -> bool:
        return (
            self.staged_path is not None
            and self.sha256 is not None
            and self.disposition is not None
            and self.disposition.get("status") == "clean"
        )

    def copy_verified_to(self, destination: Path | str) -> Path:
        """Write the exact scanned bytes and verify the copied digest."""
        if not self.is_publishable or self.staged_path is None or self.sha256 is None:
            raise RuntimeError(
                "publication candidate did not pass a complete text scan"
            )
        target = Path(destination)
        target.parent.mkdir(parents=True, exist_ok=True)
        fd, name = tempfile.mkstemp(
            prefix=f".{target.name}.", suffix=".scan.tmp", dir=target.parent
        )
        temp_path = Path(name)
        try:
            with os.fdopen(fd, "wb") as output, self.staged_path.open("rb") as source:
                shutil.copyfileobj(source, output, length=1024 * 1024)
                output.flush()
                os.fsync(output.fileno())
            copied_digest = _sha256_file(temp_path)
            if copied_digest != self.sha256:
                raise RuntimeError(
                    "staged publication candidate changed after scanning"
                )
            os.replace(temp_path, target)
            return target
        finally:
            try:
                temp_path.unlink()
            except FileNotFoundError:
                pass


@contextmanager
def scan_publication_candidate(
    source: Path | str,
    *,
    max_bytes: int,
    env: dict[str, str] | None = None,
) -> Iterator[ScannedPublicationCandidate]:
    """Copy and scan text privately; only the yielded copy can be published.

    Callers use this only for text. Binary media needs its existing explicit
    media handling because the attachment scanner intentionally skips binary
    bytes. Oversized input is hashed with bounded memory and withheld as
    unverified; the scanner limit is never increased.
    """
    path = Path(source)
    try:
        staging_root = _private_scan_root()
    except PublicationDrainTimedOut:
        raise
    except OSError:
        yield _unverified_candidate(None, None, None, "scan_error")
        return
    with tempfile.TemporaryDirectory(prefix="candidate-", dir=staging_root) as temp_dir:
        staged_path = Path(temp_dir) / "candidate"
        try:
            source_fd = os.open(
                path,
                os.O_RDONLY
                | getattr(os, "O_NOFOLLOW", 0)
                | getattr(os, "O_NONBLOCK", 0),
            )
        except PublicationDrainTimedOut:
            raise
        except OSError:
            yield _unverified_candidate(None, None, None, "scan_error")
            return
        try:
            source_stat = os.fstat(source_fd)
        except PublicationDrainTimedOut:
            raise
        except OSError:
            os.close(source_fd)
            yield _unverified_candidate(None, None, None, "scan_error")
            return
        if not stat.S_ISREG(source_stat.st_mode):
            os.close(source_fd)
            yield _unverified_candidate(None, None, None, "scan_error")
            return

        if source_stat.st_size > max_bytes:
            try:
                oversize_digest = _hash_open_file(source_fd)
            except PublicationDrainTimedOut:
                raise
            except OSError:
                os.close(source_fd)
                yield _unverified_candidate(None, None, None, "scan_error")
                return
            finally:
                try:
                    os.close(source_fd)
                except PublicationDrainTimedOut:
                    raise
                except OSError:
                    pass
            scan_result, scan_failure = _scan_file(
                path,
                max_bytes=max_bytes,
                env=env,
            )
            if scan_result is not None and scan_result.get("outcome") == "skipped":
                disposition = _disposition(scan=scan_result)
            else:
                disposition = _disposition(failure=scan_failure or "scan_error")
            yield ScannedPublicationCandidate(
                None, oversize_digest, source_stat.st_size, disposition
            )
            return

        digest = hashlib.sha256()
        byte_count = 0
        try:
            with (
                os.fdopen(source_fd, "rb") as source_file,
                staged_path.open("xb") as target,
            ):
                os.chmod(staged_path, 0o600)
                while chunk := source_file.read(1024 * 1024):
                    target.write(chunk)
                    digest.update(chunk)
                    byte_count += len(chunk)
                target.flush()
                os.fsync(target.fileno())
        except PublicationDrainTimedOut:
            raise
        except OSError:
            yield _unverified_candidate(None, None, None, "scan_error")
            return

        digest_hex = digest.hexdigest()
        scan_result, scan_failure = _scan_file(
            staged_path,
            max_bytes=max_bytes,
            env=env,
        )
        try:
            unchanged = _sha256_file(staged_path) == digest_hex
        except PublicationDrainTimedOut:
            raise
        except OSError:
            unchanged = False
        if not unchanged:
            disposition = _disposition(failure="scan_error")
        elif scan_result is None:
            disposition = _disposition(failure=scan_failure or "scan_error")
        elif scan_result.get("outcome") == "clean":
            if scan_result.get("bytes_scanned") == byte_count:
                disposition = _disposition(scan=scan_result)
            else:
                disposition = _disposition(failure="scan_error")
        else:
            disposition = _disposition(scan=scan_result)
        yield ScannedPublicationCandidate(
            staged_path,
            digest_hex,
            byte_count,
            disposition,
        )


def scan_publication_bytes(
    data: bytes,
    *,
    max_bytes: int,
    env: dict[str, str] | None = None,
) -> PublicationBytesVerdict:
    """Scan in-memory publication bytes through a private staged copy.

    Oversized input is hashed with bounded memory and withheld as unverified;
    the scanner limit is never raised to publish oversized text. A missing
    binding, scan error, or skipped result is unverified, never clean.
    """

    digest_hex = hashlib.sha256(data).hexdigest()
    if len(data) > max_bytes:
        return PublicationBytesVerdict(
            digest_hex, len(data), _disposition(failure="scan_error")
        )
    try:
        staging_root = _private_scan_root()
    except PublicationDrainTimedOut:
        raise
    except OSError:
        return PublicationBytesVerdict(
            digest_hex, len(data), _disposition(failure="scan_error")
        )
    with tempfile.TemporaryDirectory(prefix="bytes-", dir=staging_root) as temp_dir:
        staged_path = Path(temp_dir) / "candidate"
        try:
            with staged_path.open("xb") as target:
                target.write(data)
                target.flush()
                os.fsync(target.fileno())
            os.chmod(staged_path, 0o600)
        except PublicationDrainTimedOut:
            raise
        except OSError:
            return PublicationBytesVerdict(
                digest_hex, len(data), _disposition(failure="scan_error")
            )
        scan_result, scan_failure = _scan_file(
            staged_path,
            max_bytes=max_bytes,
            env=env,
        )
        try:
            unchanged = _sha256_file(staged_path) == digest_hex
        except PublicationDrainTimedOut:
            raise
        except OSError:
            unchanged = False
        if not unchanged:
            disposition = _disposition(failure="scan_error")
        elif scan_result is None:
            disposition = _disposition(failure=scan_failure or "scan_error")
        elif scan_result.get("outcome") == "clean":
            if scan_result.get("bytes_scanned") == len(data):
                disposition = _disposition(scan=scan_result)
            else:
                disposition = _disposition(failure="scan_error")
        else:
            disposition = _disposition(scan=scan_result)
        return PublicationBytesVerdict(digest_hex, len(data), disposition)


def _private_scan_root() -> Path:
    private = sase_home() / "private"
    private.mkdir(parents=True, exist_ok=True, mode=0o700)
    if private.is_symlink():
        raise OSError("private scan parent must not be a symlink")
    os.chmod(private, 0o700)
    root = private / PRIVATE_SCAN_STAGING_DIRECTORY
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    if root.is_symlink():
        raise OSError("private scan directory must not be a symlink")
    os.chmod(root, 0o700)
    return root


def _scan_file(
    path: Path,
    *,
    max_bytes: int,
    env: dict[str, str] | None,
) -> tuple[dict[str, object] | None, str | None]:
    try:
        from sase.core.rust import require_rust_binding

        binding = require_rust_binding("attachment_scan_file")
    except PublicationDrainTimedOut:
        raise
    except Exception:  # noqa: BLE001 - a missing binding never authorizes publish.
        return None, "scanner_unavailable"
    try:
        home = str(Path.home())
        try:
            from sase.core.paths import sase_home as current_sase_home

            sase_home_path = str(current_sase_home())
        except PublicationDrainTimedOut:
            raise
        except Exception:  # noqa: BLE001 - an unavailable home is no scan context.
            sase_home_path = str(Path.home() / ".sase")
        capture = dict(os.environ) if env is None else dict(env)
        result = binding(str(path), max_bytes, capture, home, sase_home_path)
    except PublicationDrainTimedOut:
        raise
    except Exception:  # noqa: BLE001 - scanner failure must withhold content.
        return None, "scan_error"
    if not isinstance(result, dict):
        return None, "scan_error"
    return dict(result), None


def _disposition(
    *,
    scan: dict[str, object] | None = None,
    failure: str | None = None,
) -> dict[str, object] | None:
    try:
        return publication_scan_disposition(scan=scan, failure=failure)
    except PublicationDrainTimedOut:
        raise
    except Exception:  # noqa: BLE001 - missing policy binding also withholds.
        return None


def _unverified_candidate(
    staged_path: Path | None,
    sha256: str | None,
    byte_count: int | None,
    failure: str,
) -> ScannedPublicationCandidate:
    return ScannedPublicationCandidate(
        staged_path,
        sha256,
        byte_count,
        _disposition(failure=failure),
    )


def _hash_open_file(handle: int) -> str:
    os.lseek(handle, 0, os.SEEK_SET)
    digest = hashlib.sha256()
    while chunk := os.read(handle, 1024 * 1024):
        digest.update(chunk)
    return digest.hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while chunk := source.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()
