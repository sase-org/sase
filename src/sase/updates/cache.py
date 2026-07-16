"""Snapshot cache for automatic update-status checks."""

from __future__ import annotations

import importlib.metadata as importlib_metadata
import json
import os
import subprocess
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from sase.core.paths import ensure_sase_directory, sase_subdir
from sase.dev_update.detect import git_status_has_update
from sase.plugins.latest import is_newer
from sase.version._git import GitUpstreamStatus, classify_git_upstream

from .status import (
    OutdatedComponent,
    UpdateStatus,
    compute_update_status,
)

SCHEMA_VERSION = 2
CACHE_SUBDIR = "updates"
CACHE_FILENAME = "status_snapshot.json"
DEFAULT_UPDATE_STATUS_TTL_SECONDS = 10 * 60

VersionFn = Callable[[str], str | None]
IsNewerFn = Callable[[str | None, str | None], bool]
ComputeStatusFn = Callable[..., UpdateStatus]
GitClassifierFn = Callable[[Path], GitUpstreamStatus]


def _cache_path() -> Path:
    return sase_subdir(CACHE_SUBDIR) / CACHE_FILENAME


def read_update_status_snapshot(path: Path | None = None) -> UpdateStatus | None:
    """Read the cached update-status snapshot, tolerating missing/corrupt data."""
    cache_path = path or _cache_path()
    try:
        raw = cache_path.read_text(encoding="utf-8")
    except OSError:
        return None
    try:
        envelope = json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        return None
    if not isinstance(envelope, dict):
        return None
    if envelope.get("schema_version") != SCHEMA_VERSION:
        return None
    checked_at = envelope.get("checked_at")
    if not isinstance(checked_at, (int, float)) or isinstance(checked_at, bool):
        return None
    raw_components = envelope.get("components")
    if not isinstance(raw_components, list):
        return None

    components: list[OutdatedComponent] = []
    for raw_component in raw_components:
        component = _component_from_json(raw_component)
        if component is not None:
            components.append(component)
    return UpdateStatus(checked_at=float(checked_at), components=tuple(components))


def write_update_status_snapshot(
    status: UpdateStatus,
    *,
    path: Path | None = None,
) -> None:
    """Atomically write *status* to the update-status snapshot cache."""
    cache_path = path or _cache_path()
    if path is None:
        ensure_sase_directory(CACHE_SUBDIR)
    else:
        cache_path.parent.mkdir(parents=True, exist_ok=True)

    envelope: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "checked_at": status.checked_at,
        "components": [
            {
                "display_name": component.display_name,
                "role": component.role,
                "installed_version": component.installed_version,
                "latest_version": component.latest_version,
                "distribution_name": component.distribution_name,
                "install_type": component.install_type,
                "source_root": component.source_root,
                "upstream_ref": component.upstream_ref,
            }
            for component in status.components
        ],
    }
    serialized = json.dumps(envelope, indent=2, sort_keys=True)
    tmp_path = cache_path.with_name(f"{cache_path.name}.{os.getpid()}.tmp")
    tmp_path.write_text(serialized, encoding="utf-8")
    os.replace(tmp_path, cache_path)


def update_status_snapshot_is_fresh(
    status: UpdateStatus,
    *,
    now: float | None = None,
    ttl_seconds: float = DEFAULT_UPDATE_STATUS_TTL_SECONDS,
) -> bool:
    """Return whether *status* is inside the requested cache TTL."""
    check_now = time.time() if now is None else now
    age = check_now - status.checked_at
    return 0 <= age < ttl_seconds


def revalidate_update_status(
    status: UpdateStatus,
    *,
    version_fn: VersionFn = importlib_metadata.version,
    is_newer_fn: IsNewerFn = is_newer,
    git_classifier_fn: GitClassifierFn = classify_git_upstream,
) -> UpdateStatus:
    """Drop cached components that no longer look outdated locally."""
    components = tuple(
        component
        for component in status.components
        if _component_still_outdated(
            component,
            version_fn=version_fn,
            is_newer_fn=is_newer_fn,
            git_classifier_fn=git_classifier_fn,
        )
    )
    if components == status.components:
        return status
    return UpdateStatus(checked_at=status.checked_at, components=components)


def get_cached_update_status(
    *,
    ttl_seconds: float = DEFAULT_UPDATE_STATUS_TTL_SECONDS,
    offline: bool = False,
    refresh: bool = False,
    revalidate_only: bool = False,
    now: float | None = None,
    path: Path | None = None,
    compute_fn: ComputeStatusFn = compute_update_status,
    version_fn: VersionFn = importlib_metadata.version,
    is_newer_fn: IsNewerFn = is_newer,
    git_classifier_fn: GitClassifierFn = classify_git_upstream,
) -> UpdateStatus | None:
    """Return a cached update status, optionally recomputing when it is stale.

    When ``revalidate_only`` is true, this function never calls ``compute_fn``.
    It returns the locally revalidated snapshot regardless of its age, or
    ``None`` when no usable snapshot exists.
    """
    check_now = time.time() if now is None else now
    cached = read_update_status_snapshot(path=path)
    if cached is not None and (
        revalidate_only
        or (
            not refresh
            and update_status_snapshot_is_fresh(
                cached,
                now=check_now,
                ttl_seconds=ttl_seconds,
            )
        )
    ):
        return revalidate_update_status(
            cached,
            version_fn=version_fn,
            is_newer_fn=is_newer_fn,
            git_classifier_fn=git_classifier_fn,
        )
    if revalidate_only:
        return None

    try:
        status = compute_fn(offline=offline, refresh=refresh, now=check_now)
    except Exception:  # noqa: BLE001 - startup should fall back or stay silent.
        if cached is not None:
            return revalidate_update_status(
                cached,
                version_fn=version_fn,
                is_newer_fn=is_newer_fn,
                git_classifier_fn=git_classifier_fn,
            )
        return None

    try:
        write_update_status_snapshot(status, path=path)
    except Exception:  # noqa: BLE001 - cache writes are best effort.
        pass
    return revalidate_update_status(
        status,
        version_fn=version_fn,
        is_newer_fn=is_newer_fn,
        git_classifier_fn=git_classifier_fn,
    )


def _component_from_json(raw: object) -> OutdatedComponent | None:
    if not isinstance(raw, dict):
        return None
    display_name = raw.get("display_name")
    role = raw.get("role")
    installed_version = raw.get("installed_version")
    latest_version = raw.get("latest_version")
    distribution_name = raw.get("distribution_name")
    install_type = raw.get("install_type")
    source_root = raw.get("source_root")
    upstream_ref = raw.get("upstream_ref")
    if not isinstance(display_name, str) or not display_name:
        return None
    if role not in {"host", "core", "plugin"}:
        return None
    if installed_version is not None and not isinstance(installed_version, str):
        return None
    if latest_version is not None and not isinstance(latest_version, str):
        return None
    if not isinstance(distribution_name, str) or not distribution_name:
        return None
    if install_type is not None and not isinstance(install_type, str):
        return None
    if source_root is not None and not isinstance(source_root, str):
        return None
    if upstream_ref is not None and not isinstance(upstream_ref, str):
        return None
    return OutdatedComponent(
        display_name=display_name,
        role=role,
        installed_version=installed_version,
        latest_version=latest_version,
        distribution_name=distribution_name,
        install_type=install_type,
        source_root=source_root,
        upstream_ref=upstream_ref,
    )


def _component_still_outdated(
    component: OutdatedComponent,
    *,
    version_fn: VersionFn,
    is_newer_fn: IsNewerFn,
    git_classifier_fn: GitClassifierFn,
) -> bool:
    if component.install_type == "editable" and component.source_root:
        return _editable_component_still_outdated(
            component,
            git_classifier_fn=git_classifier_fn,
        )
    try:
        live_version = version_fn(component.distribution_name)
    except importlib_metadata.PackageNotFoundError:
        return False
    except Exception:  # noqa: BLE001 - broken metadata suppresses stale toast rows.
        return False
    return is_newer_fn(component.latest_version, live_version)


def _editable_component_still_outdated(
    component: OutdatedComponent,
    *,
    git_classifier_fn: GitClassifierFn,
) -> bool:
    try:
        status = git_classifier_fn(Path(component.source_root or ""))
    except (
        FileNotFoundError,
        OSError,
        subprocess.CalledProcessError,
        subprocess.TimeoutExpired,
    ):
        return True
    except Exception:  # noqa: BLE001 - conservative cache revalidation.
        return True
    return git_status_has_update(status)


__all__ = [
    "CACHE_FILENAME",
    "CACHE_SUBDIR",
    "DEFAULT_UPDATE_STATUS_TTL_SECONDS",
    "SCHEMA_VERSION",
    "get_cached_update_status",
    "read_update_status_snapshot",
    "revalidate_update_status",
    "update_status_snapshot_is_fresh",
    "write_update_status_snapshot",
]
