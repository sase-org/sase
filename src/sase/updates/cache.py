"""Snapshot cache for automatic update-status checks."""

from __future__ import annotations

import importlib.metadata as importlib_metadata
import json
import math
import os
import subprocess
import time
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path
from typing import Any

from sase.agent_clis.models import AgentCliStatus, UpdateStrategy
from sase.agent_clis.operations import (
    detect_agent_cli_statuses_for_names,
    plan_agent_cli_status,
)
from sase.core.paths import ensure_sase_directory, sase_subdir
from sase.dev_update.detect import git_status_has_update
from sase.plugins.latest import is_newer
from sase.version._git import GitUpstreamStatus, classify_git_upstream

from .status import (
    OutdatedComponent,
    ProviderUpdateCandidate,
    UpdateSourceStatus,
    UpdateStatus,
    compute_update_status,
)

SCHEMA_VERSION = 4
CACHE_SUBDIR = "updates"
CACHE_FILENAME = "status_snapshot.json"
DEFAULT_UPDATE_STATUS_TTL_SECONDS = 10 * 60

VersionFn = Callable[[str], str | None]
IsNewerFn = Callable[[str | None, str | None], bool]
ComputeStatusFn = Callable[..., UpdateStatus]
GitClassifierFn = Callable[[Path], GitUpstreamStatus]
ProviderStatusFn = Callable[..., tuple[AgentCliStatus, ...]]


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
    checked_at = _timestamp_from_json(envelope.get("checked_at"))
    if checked_at is None:
        return None
    raw_components = envelope.get("components")
    if not isinstance(raw_components, list):
        return None

    components: list[OutdatedComponent] = []
    for raw_component in raw_components:
        component = _component_from_json(raw_component)
        if component is None:
            return None
        components.append(component)

    raw_candidates = envelope.get("provider_candidates")
    if not isinstance(raw_candidates, list):
        return None
    provider_candidates: list[ProviderUpdateCandidate] = []
    seen_providers: set[str] = set()
    for raw_candidate in raw_candidates:
        candidate = _provider_candidate_from_json(raw_candidate)
        if candidate is None or candidate.provider in seen_providers:
            return None
        provider_candidates.append(candidate)
        seen_providers.add(candidate.provider)

    raw_sources = envelope.get("sources")
    if not isinstance(raw_sources, dict):
        return None
    core_source = _source_from_json(raw_sources.get("core"))
    plugin_source = _source_from_json(raw_sources.get("plugins"))
    agent_cli_source = _source_from_json(raw_sources.get("agent_clis"))
    if core_source is None or plugin_source is None or agent_cli_source is None:
        return None
    return UpdateStatus(
        checked_at=checked_at,
        components=tuple(components),
        provider_candidates=tuple(provider_candidates),
        core_source=core_source,
        plugin_source=plugin_source,
        agent_cli_source=agent_cli_source,
    )


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
        "provider_candidates": [
            {
                "provider": candidate.provider,
                "display_name": candidate.display_name,
                "installed_version": candidate.installed_version,
                "latest_version": candidate.latest_version,
                "manual_only": candidate.manual_only,
            }
            for candidate in status.provider_candidates
        ],
        "sources": {
            "core": _source_to_json(status.core_source),
            "plugins": _source_to_json(status.plugin_source),
            "agent_clis": _source_to_json(status.agent_cli_source),
        },
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
    provider_status_fn: ProviderStatusFn = detect_agent_cli_statuses_for_names,
) -> UpdateStatus:
    """Drop cached components/providers that no longer look outdated locally.

    This is deliberately a drop-only, no-network operation: it can remove
    stale rows but cannot discover components that became outdated after the
    snapshot was written. Use a full recompute to grow the component set.
    """
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
    provider_candidates = revalidate_provider_candidates(
        status.provider_candidates,
        status_fn=provider_status_fn,
        is_newer_fn=is_newer_fn,
    )
    if (
        components == status.components
        and provider_candidates == status.provider_candidates
    ):
        return status
    return replace(
        status,
        components=components,
        provider_candidates=provider_candidates,
    )


def revalidate_provider_candidates(
    candidates: tuple[ProviderUpdateCandidate, ...],
    *,
    status_fn: ProviderStatusFn = detect_agent_cli_statuses_for_names,
    is_newer_fn: IsNewerFn = is_newer,
) -> tuple[ProviderUpdateCandidate, ...]:
    """Locally revalidate only cached provider names, conservatively.

    No registry metadata, cache file, subprocess, or network work occurs for an
    empty candidate set.  Probe failures retain prior evidence; proven absence
    or a live current version drops the candidate.
    """
    if not candidates:
        return ()
    names = tuple(candidate.provider for candidate in candidates)
    try:
        statuses = status_fn(names)
    except Exception:  # noqa: BLE001 - transient local failures retain evidence.
        return candidates
    by_provider = {status.provider: status for status in statuses}
    kept: list[ProviderUpdateCandidate] = []
    for candidate in candidates:
        live = by_provider.get(candidate.provider)
        if live is None or not live.installed:
            continue
        if live.version_error or live.installed_version is None:
            kept.append(candidate)
            continue
        if is_newer_fn(candidate.latest_version, live.installed_version):
            kept.append(
                replace(
                    candidate,
                    installed_version=live.installed_version,
                    manual_only=(
                        plan_agent_cli_status(live).strategy is UpdateStrategy.MANUAL
                    ),
                )
            )
    return tuple(kept)


def merge_update_status(
    previous: UpdateStatus | None,
    current: UpdateStatus,
) -> UpdateStatus:
    """Merge a composite result source-by-source with last-known-good state."""
    if previous is None:
        previous = UpdateStatus(checked_at=current.checked_at, components=())

    previous_core, previous_plugins = _split_components(previous.components)
    current_core, current_plugins = _split_components(current.components)
    core, core_source = _merge_source(
        previous_core,
        previous.core_source,
        current_core,
        current.core_source,
    )
    plugins, plugin_source = _merge_source(
        previous_plugins,
        previous.plugin_source,
        current_plugins,
        current.plugin_source,
    )
    providers, agent_cli_source = _merge_source(
        previous.provider_candidates,
        previous.agent_cli_source,
        current.provider_candidates,
        current.agent_cli_source,
    )
    components = tuple(
        sorted(
            (*core, *plugins),
            key=lambda item: (
                _role_sort_key(item.role),
                item.display_name.casefold(),
            ),
        )
    )
    return UpdateStatus(
        checked_at=current.checked_at,
        components=components,
        provider_candidates=tuple(
            sorted(providers, key=lambda item: item.provider.casefold())
        ),
        core_source=core_source,
        plugin_source=plugin_source,
        agent_cli_source=agent_cli_source,
    )


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
    provider_status_fn: ProviderStatusFn = detect_agent_cli_statuses_for_names,
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
        status = revalidate_update_status(
            cached,
            version_fn=version_fn,
            is_newer_fn=is_newer_fn,
            git_classifier_fn=git_classifier_fn,
            provider_status_fn=provider_status_fn,
        )
        _write_revalidated_if_changed(cached, status, path=path)
        return status
    if revalidate_only:
        return None

    try:
        status = compute_fn(offline=offline, refresh=refresh, now=check_now)
    except Exception:  # noqa: BLE001 - startup should fall back or stay silent.
        if cached is not None:
            status = revalidate_update_status(
                cached,
                version_fn=version_fn,
                is_newer_fn=is_newer_fn,
                git_classifier_fn=git_classifier_fn,
                provider_status_fn=provider_status_fn,
            )
            _write_revalidated_if_changed(cached, status, path=path)
            return status
        return None

    status = merge_update_status(cached, status)
    try:
        write_update_status_snapshot(status, path=path)
    except Exception:  # noqa: BLE001 - cache writes are best effort.
        pass
    return status


def _write_revalidated_if_changed(
    before: UpdateStatus,
    after: UpdateStatus,
    *,
    path: Path | None,
) -> None:
    if after == before:
        return
    try:
        write_update_status_snapshot(after, path=path)
    except Exception:  # noqa: BLE001 - cache writes are best effort.
        return


def _source_to_json(source: UpdateSourceStatus) -> dict[str, Any]:
    return {"checked_at": source.checked_at, "error": source.error}


def _source_from_json(raw: object) -> UpdateSourceStatus | None:
    if not isinstance(raw, dict):
        return None
    raw_checked_at = raw.get("checked_at")
    checked_at = (
        None if raw_checked_at is None else _timestamp_from_json(raw_checked_at)
    )
    if raw_checked_at is not None and checked_at is None:
        return None
    error = raw.get("error")
    if error is not None and (not isinstance(error, str) or not error.strip()):
        return None
    if checked_at is None and error is None:
        return UpdateSourceStatus()
    return UpdateSourceStatus(checked_at=checked_at, error=error)


def _provider_candidate_from_json(raw: object) -> ProviderUpdateCandidate | None:
    if not isinstance(raw, dict):
        return None
    provider = raw.get("provider")
    display_name = raw.get("display_name")
    installed_version = raw.get("installed_version")
    latest_version = raw.get("latest_version")
    manual_only = raw.get("manual_only")
    if not isinstance(provider, str) or not provider:
        return None
    if not isinstance(display_name, str) or not display_name:
        return None
    if not isinstance(installed_version, str) or not installed_version:
        return None
    if not isinstance(latest_version, str) or not latest_version:
        return None
    if not isinstance(manual_only, bool):
        return None
    return ProviderUpdateCandidate(
        provider=provider,
        display_name=display_name,
        installed_version=installed_version,
        latest_version=latest_version,
        manual_only=manual_only,
    )


def _timestamp_from_json(raw: object) -> float | None:
    if not isinstance(raw, (int, float)) or isinstance(raw, bool):
        return None
    value = float(raw)
    return value if math.isfinite(value) and value >= 0 else None


def _split_components(
    components: tuple[OutdatedComponent, ...],
) -> tuple[tuple[OutdatedComponent, ...], tuple[OutdatedComponent, ...]]:
    core = tuple(component for component in components if component.role != "plugin")
    plugins = tuple(component for component in components if component.role == "plugin")
    return core, plugins


def _merge_source[T](
    previous_items: tuple[T, ...],
    previous_source: UpdateSourceStatus,
    current_items: tuple[T, ...],
    current_source: UpdateSourceStatus,
) -> tuple[tuple[T, ...], UpdateSourceStatus]:
    if current_source.successful:
        return current_items, current_source
    if current_source.error is not None:
        return previous_items, UpdateSourceStatus(
            checked_at=previous_source.checked_at,
            error=current_source.error,
        )
    return previous_items, previous_source


def _role_sort_key(role: str) -> int:
    if role == "host":
        return 0
    if role == "core":
        return 1
    return 2


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
    except Exception:  # noqa: BLE001 - transient local failures retain evidence.
        return True
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
    "merge_update_status",
    "read_update_status_snapshot",
    "revalidate_provider_candidates",
    "revalidate_update_status",
    "update_status_snapshot_is_fresh",
    "write_update_status_snapshot",
]
