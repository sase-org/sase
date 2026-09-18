"""Path, identity, and PNG-header helpers for visual candidate capture."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import os
from pathlib import Path
import tempfile


SCHEMA_VERSION = 1
PLUGIN_NAME = "sase-visual-capture"
DEFAULT_ACE_ROOT = "tests/ace/tui/visual/snapshots/png"
DEFAULT_PAGER_ROOT = "tests/pager/visual/snapshots/png"
ACE_TEST_PREFIX = "tests/ace/tui/visual/"
PAGER_TEST_PREFIX = "tests/pager/visual/"
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
_WORKER_ID_CHARS = frozenset(
    "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._-"
)


class VisualCaptureError(ValueError):
    """Invalid visual capture request, path, or worker identity."""


@dataclass(frozen=True)
class VisualCaptureRoots:
    """ACE and pager PNG golden roots for one capture run."""

    ace: Path
    pager: Path

    def path_for(self, identity: str) -> Path:
        if identity == "ace":
            return self.ace
        if identity == "pager":
            return self.pager
        raise VisualCaptureError(f"unknown visual root identity: {identity!r}")

    def identity_for(self, snapshot_root: Path) -> str | None:
        try:
            resolved = snapshot_root.resolve()
        except OSError:
            return None
        try:
            if resolved == self.ace.resolve():
                return "ace"
        except OSError:
            pass
        try:
            if resolved == self.pager.resolve():
                return "pager"
        except OSError:
            pass
        return None


def sanitize_worker_id(worker_id: str) -> str:
    """Return *worker_id* when it is a single safe path component."""
    if (
        not worker_id
        or worker_id in {".", ".."}
        or any(char not in _WORKER_ID_CHARS for char in worker_id)
    ):
        raise VisualCaptureError(f"invalid worker id: {worker_id!r}")
    return worker_id


def worker_directory(capture_dir: Path, worker_id: str) -> Path:
    """Return the worker-local directory under *capture_dir*."""
    return capture_dir / "workers" / sanitize_worker_id(worker_id)


def capture_artifact_id(
    *,
    node_id: str,
    canonical_golden_path: str,
    sequence: int,
    worker_id: str,
) -> str:
    """Return a collision-resistant artifact id for one capture."""
    payload = f"{node_id}\0{canonical_golden_path}\0{sequence}\0{worker_id}".encode()
    return hashlib.sha256(payload).hexdigest()


def png_dimensions(png_bytes: bytes) -> tuple[int, int]:
    """Return ``(width, height)`` from a PNG IHDR without decoding pixels."""
    if len(png_bytes) < 24 or png_bytes[:8] != PNG_SIGNATURE:
        raise VisualCaptureError("candidate is not a PNG")
    length = int.from_bytes(png_bytes[8:12], "big")
    chunk_type = png_bytes[12:16]
    if chunk_type != b"IHDR" or length != 13:
        raise VisualCaptureError("candidate PNG is missing IHDR")
    width = int.from_bytes(png_bytes[16:20], "big")
    height = int.from_bytes(png_bytes[20:24], "big")
    if width < 1 or height < 1:
        raise VisualCaptureError("candidate PNG has invalid dimensions")
    return width, height


def sha256_bytes(value: bytes) -> str:
    """Return the hex SHA-256 digest of *value*."""
    return hashlib.sha256(value).hexdigest()


def hash_file_tree(root: Path) -> str:
    """Return a stable SHA-256 of every regular file under *root*."""
    digest = hashlib.sha256()
    if not root.exists():
        return digest.hexdigest()
    files = sorted(
        path for path in root.rglob("*") if path.is_file() and not path.is_symlink()
    )
    for path in files:
        relative = path.relative_to(root).as_posix().encode()
        digest.update(relative)
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def visual_root_for_nodeid(nodeid: str) -> str | None:
    """Return ``ace`` or ``pager`` when *nodeid* lives under a visual tree."""
    relative = nodeid.split("::", 1)[0].replace("\\", "/")
    if relative.startswith(ACE_TEST_PREFIX):
        return "ace"
    if relative.startswith(PAGER_TEST_PREFIX):
        return "pager"
    return None


def canonical_golden_path(
    *,
    snapshot_root: Path,
    name: str,
    repo_root: Path,
    roots: VisualCaptureRoots,
) -> tuple[str, str]:
    """Return ``(root_identity, repo-relative golden path)`` for *name*.

    Rejects absolute names, ``..`` traversal, and symlink escapes from the
    ACE or pager PNG roots.
    """
    identity = roots.identity_for(snapshot_root)
    if identity is None:
        raise VisualCaptureError(
            f"snapshot root {snapshot_root} is not the ACE or pager PNG root"
        )
    relative = _snapshot_relative_name(name)
    root = roots.path_for(identity).resolve()
    candidate = root / relative
    try:
        resolved = candidate.resolve()
    except OSError as exc:
        raise VisualCaptureError(f"invalid snapshot name: {name!r}") from exc
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise VisualCaptureError(
            f"snapshot path escapes {identity} PNG root: {name!r}"
        ) from exc
    try:
        repo_relative = resolved.relative_to(repo_root.resolve()).as_posix()
    except ValueError as exc:
        raise VisualCaptureError(
            f"snapshot path is outside the repository: {name!r}"
        ) from exc
    if ".." in Path(repo_relative).parts:
        raise VisualCaptureError(f"invalid snapshot name: {name!r}")
    return identity, repo_relative


def _snapshot_relative_name(name: str) -> Path:
    if not name or name.endswith("/") or name.endswith("\\"):
        raise VisualCaptureError(f"invalid snapshot name: {name!r}")
    path = Path(name)
    if path.is_absolute() or ".." in path.parts or path.parts[:1] == ("~",):
        raise VisualCaptureError(f"invalid snapshot name: {name!r}")
    if any(part in {"", "."} for part in path.parts):
        raise VisualCaptureError(f"invalid snapshot name: {name!r}")
    if path.suffix != ".png":
        path = path.with_suffix(".png")
    return path


def atomic_write_bytes(path: Path, data: bytes) -> None:
    """Write *data* to *path* via a same-directory replace."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        tmp_path.replace(path)
    except Exception:
        tmp_path.unlink(missing_ok=True)
        raise


def atomic_write_text(path: Path, text: str) -> None:
    """Write UTF-8 *text* to *path* via a same-directory replace."""
    atomic_write_bytes(path, text.encode("utf-8"))
