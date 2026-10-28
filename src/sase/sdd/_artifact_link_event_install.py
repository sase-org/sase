"""Atomic installation of immutable artifact-link event objects."""

from __future__ import annotations

from collections.abc import Sequence
import os
from pathlib import Path
import subprocess
from uuid import uuid4

from sase.core.rust import require_rust_binding
from sase.sdd._artifact_link_event_canonical import (
    ArtifactLinkEventCorruptionError,
    ArtifactLinkEventObject,
    ArtifactLinkEventPublishError,
)


def install_artifact_link_bytes(
    root: str | Path,
    relative_path: str | Path,
    payload: bytes,
    *,
    staging_dir: str | Path | None = None,
) -> bool:
    """Install *payload* at *relative_path* with atomic no-replace plus fsync."""

    root = Path(root).expanduser().resolve(strict=False)
    relative = Path(relative_path)
    if relative.is_absolute() or ".." in relative.parts:
        raise ArtifactLinkEventCorruptionError(
            f"artifact-link path must be a relative file path: {relative}"
        )
    final_path = root / relative
    if _existing_bytes_are_installed(root, final_path, payload):
        return False

    final_path.parent.mkdir(parents=True, exist_ok=True)
    staging_root = (
        Path(staging_dir) if staging_dir is not None else relative.parent / ".staging"
    )
    if not staging_root.is_absolute():
        staging_root = root / staging_root
    staging_root.mkdir(parents=True, exist_ok=True)
    staging = staging_root / f"{final_path.name}.{os.getpid()}.{uuid4().hex}.tmp"
    fd = os.open(staging, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        while True:
            try:
                os.link(staging, final_path)
                created = True
                break
            except FileExistsError:
                if _existing_bytes_are_installed(root, final_path, payload):
                    created = False
                    break
    except BaseException:
        raise
    finally:
        try:
            staging.unlink()
        except FileNotFoundError:
            pass
    _fsync_directory(final_path.parent)
    return created


def install_artifact_link_event_object(
    root: str | Path,
    item: ArtifactLinkEventObject,
) -> bool:
    """Install *item* at its content-addressed path with atomic no-replace."""

    return install_artifact_link_bytes(
        root,
        item.relative_path,
        item.payload,
        staging_dir=Path("link-events") / "v1" / ".staging",
    )


def clean_artifact_link_event_staging(root: str | Path) -> int:
    """Remove leftover staged event temp files under one event store root."""

    staging_dir = (
        Path(root).expanduser().resolve(strict=False)
        / "link-events"
        / "v1"
        / ".staging"
    )
    if not staging_dir.is_dir():
        return 0
    removed = 0
    for path in sorted(staging_dir.iterdir()):
        if not path.name.endswith(".tmp"):
            continue
        if not path.is_file() and not path.is_symlink():
            continue
        try:
            path.unlink()
            removed += 1
        except FileNotFoundError:
            pass
    if removed:
        _fsync_directory(staging_dir)
    return removed


def verify_artifact_link_operation_selection(
    root: str | Path,
    objects: Sequence[ArtifactLinkEventObject],
) -> None:
    """Recheck the core-selected winners against one locked event root.

    The publication lock performs the full cross-root partition before any
    projection or installation. This narrower check runs after taking a root's
    Git write lock, so a concurrent durable replay cannot slip between that
    selection and the write. A newly observed collision asks the caller to
    retry; the next full partition will quarantine it with complete evidence.
    """

    from sase.sdd._artifact_link_event_collision import (
        candidate_from_event,
        partition_artifact_link_candidates,
    )

    root = Path(root).expanduser().resolve(strict=False)
    operation_ids = {str(item.event["operation_id"]) for item in objects}
    candidates = []
    event_root = root / "link-events" / "v1"
    if event_root.is_dir():
        for path in sorted(event_root.rglob("*.json")):
            if path.is_symlink():
                raise ArtifactLinkEventCorruptionError(
                    f"artifact-link event path is a symlink: {path}"
                )
            if not path.is_file():
                continue
            relative = path.relative_to(root).as_posix()
            try:
                validated = require_rust_binding("artifact_link_event_validate_bytes")(
                    path.read_bytes(), relative
                )
                event = dict(validated["event"])
            except Exception as exc:
                raise ArtifactLinkEventCorruptionError(
                    f"artifact-link event path is invalid: {path}: {exc}"
                ) from exc
            if str(event.get("operation_id") or "") not in operation_ids:
                continue
            candidates.append(
                candidate_from_event(
                    event,
                    tier="durable",
                    source_locator=f"recheck:{relative}",
                    root=str(root),
                    relative_path=relative,
                    digest=str(validated["digest"]),
                    canonical_json=str(validated["canonical_json"]),
                )
            )
    candidates.extend(
        candidate_from_event(
            item.event,
            tier="incoming",
            source_locator=f"recheck:incoming:{item.event['operation_id']}",
            digest=item.digest,
            canonical_json=item.canonical_json,
        )
        for item in objects
    )
    partition = partition_artifact_link_candidates(candidates)
    accepted_digests = {item.digest for item in partition.accepted}
    rejected = [item for item in objects if item.digest not in accepted_digests]
    if rejected:
        item = rejected[0]
        raise ArtifactLinkEventPublishError(
            f"artifact-link event selection changed while publishing operation_id "
            f"`{item.event['operation_id']}`; retry to quarantine the replay"
        )


def artifact_link_bytes_are_durable(
    root: str | Path,
    relative_path: str | Path,
    payload: bytes,
) -> bool:
    """Return whether *root* durably contains these exact bytes at one path."""

    root = Path(root).expanduser().resolve(strict=False)
    relative = Path(relative_path)
    if relative.is_absolute() or ".." in relative.parts:
        return False
    if _is_git_repo(root):
        result = _git_show(root, relative.as_posix())
        return result is not None and result.stdout == payload
    try:
        path = root / relative
        return not path.is_symlink() and path.read_bytes() == payload
    except OSError:
        return False


def event_object_is_durable(
    root: str | Path,
    item: ArtifactLinkEventObject,
) -> bool:
    """Return whether *root* durably contains *item*'s exact event object."""

    root = Path(root).expanduser().resolve(strict=False)
    if _is_git_repo(root):
        return _head_contains_event(root, item)
    return _working_tree_contains_event(root, item)


def _existing_bytes_are_installed(root: Path, path: Path, payload: bytes) -> bool:
    if path.is_symlink():
        raise ArtifactLinkEventCorruptionError(
            f"artifact-link event path is a symlink: {path}"
        )
    if not path.exists():
        return False
    if not path.is_file():
        raise ArtifactLinkEventCorruptionError(
            f"artifact-link event path is not a regular file: {path}"
        )
    try:
        existing = path.read_bytes()
    except OSError as exc:
        raise ArtifactLinkEventPublishError(
            f"could not read existing artifact-link event {path}: {exc}"
        ) from exc
    if existing == payload:
        return True
    if not existing and not _head_contains_path(root, path):
        path.unlink()
        _fsync_directory(path.parent)
        return False
    raise ArtifactLinkEventCorruptionError(
        f"artifact-link event path already exists with different bytes: {path}"
    )


def _head_contains_event(root: Path, item: ArtifactLinkEventObject) -> bool:
    result = _git_show(root, item.relative_path.as_posix())
    return result is not None and result.stdout == item.payload


def _head_contains_path(root: Path, path: Path) -> bool:
    try:
        relative = path.relative_to(root).as_posix()
    except ValueError:
        return False
    return _git_show(root, relative) is not None


def _git_show(
    root: Path,
    relative_path: str,
) -> subprocess.CompletedProcess[bytes] | None:
    result = subprocess.run(
        ["git", "show", f"HEAD:{relative_path}"],
        cwd=root,
        capture_output=True,
        check=False,
    )
    return result if result.returncode == 0 else None


def _is_git_repo(root: Path) -> bool:
    result = subprocess.run(
        ["git", "rev-parse", "--is-inside-work-tree"],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )
    return result.returncode == 0


def _working_tree_contains_event(root: Path, item: ArtifactLinkEventObject) -> bool:
    try:
        return (root / item.relative_path).read_bytes() == item.payload
    except OSError:
        return False


def _fsync_directory(path: Path) -> None:
    try:
        fd = os.open(path, os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


__all__ = [
    "artifact_link_bytes_are_durable",
    "clean_artifact_link_event_staging",
    "event_object_is_durable",
    "install_artifact_link_bytes",
    "install_artifact_link_event_object",
    "verify_artifact_link_operation_selection",
]
