"""Atomic installation of immutable artifact-link event objects."""

from __future__ import annotations

from collections.abc import Sequence
import json
import os
from pathlib import Path
import subprocess
from uuid import uuid4

from sase.sdd._artifact_link_event_canonical import (
    ArtifactLinkEventCorruptionError,
    ArtifactLinkEventObject,
    ArtifactLinkEventPublishError,
    canonical_artifact_link_event_object,
)


def install_artifact_link_event_object(
    root: str | Path,
    item: ArtifactLinkEventObject,
) -> bool:
    """Install *item* at its content-addressed path with atomic no-replace."""

    root = Path(root).expanduser().resolve(strict=False)
    final_path = root / item.relative_path
    if _existing_event_is_installed(root, final_path, item.payload):
        return False

    final_path.parent.mkdir(parents=True, exist_ok=True)
    staging_dir = root / "link-events" / "v1" / ".staging"
    staging_dir.mkdir(parents=True, exist_ok=True)
    staging = staging_dir / f"{item.digest}.{os.getpid()}.{uuid4().hex}.tmp"
    fd = os.open(staging, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(item.payload)
            stream.flush()
            os.fsync(stream.fileno())
        while True:
            try:
                os.link(staging, final_path)
                created = True
                break
            except FileExistsError:
                if _existing_event_is_installed(root, final_path, item.payload):
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


def reject_existing_operation_collisions(
    root: str | Path,
    objects: Sequence[ArtifactLinkEventObject],
) -> None:
    """Reject reused operation IDs with different existing event bytes."""

    root = Path(root).expanduser().resolve(strict=False)
    by_operation = {str(item.event["operation_id"]): item for item in objects}
    event_root = root / "link-events" / "v1"
    if not event_root.is_dir():
        return
    for path in sorted(event_root.rglob("*.json")):
        if not path.is_file():
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(data, dict):
            continue
        operation_id = str(data.get("operation_id") or "")
        incoming = by_operation.get(operation_id)
        if incoming is None:
            continue
        try:
            existing = canonical_artifact_link_event_object(data)
        except Exception as exc:
            raise ArtifactLinkEventCorruptionError(
                f"artifact-link event path for operation_id `{operation_id}` "
                f"is invalid: {path}: {exc}"
            ) from exc
        if existing.payload != incoming.payload:
            raise ArtifactLinkEventCorruptionError(
                f"operation_id `{operation_id}` was reused for different "
                f"artifact-link event bytes already present at {path}"
            )


def event_object_is_durable(
    root: str | Path,
    item: ArtifactLinkEventObject,
) -> bool:
    """Return whether *root* durably contains *item*'s exact event object."""

    root = Path(root).expanduser().resolve(strict=False)
    if _is_git_repo(root):
        return _head_contains_event(root, item)
    return _working_tree_contains_event(root, item)


def _existing_event_is_installed(root: Path, path: Path, payload: bytes) -> bool:
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
    "clean_artifact_link_event_staging",
    "event_object_is_durable",
    "install_artifact_link_event_object",
    "reject_existing_operation_collisions",
]
