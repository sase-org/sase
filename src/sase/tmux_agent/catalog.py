"""Assemble the tmux Agent catalog from registry, config, and detection state."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
import os
from typing import Any, cast

from sase.agent_clis.detect import resolve_executable
from sase.agent_clis.models import AgentCliStatus
from sase.agent_clis.operations import collect_agent_cli_statuses
from sase.config.tmux_agent import (
    TmuxAgentConfig,
    TmuxAgentProviderConfig,
    get_tmux_agent_config,
)
from sase.llm_provider import (
    effective_default_effort_snapshot,
    get_active_provider_disables,
)
from sase.llm_provider import registry as llm_registry
from sase.llm_provider.config import get_llm_provider_config
from sase.llm_provider.provider_disable import TemporaryProviderDisable

from .cache import (
    CachedProvider,
    CatalogCachePayload,
    load_catalog_payload,
)
from .keys import MenuKeyCandidate, assign_menu_keys
from .launch_spec import (
    InvocationOptionProvider,
    resolve_effort_level,
    resolve_launch_argv,
)
from .models import TmuxAgentCatalog, TmuxAgentEntry

ResolveExecutableFn = Callable[[str, str], str | None]
DisablesFn = Callable[[float | None], Mapping[str, TemporaryProviderDisable]]


@dataclass(frozen=True)
class _ResolvedProvider:
    """One included provider after registry/config resolution."""

    provider: str
    display_name: str
    vendor: str
    color: str
    key: str
    binary: str
    executable: str | None
    installed: bool
    install_hint: str
    routing_disabled: TemporaryProviderDisable | None
    argv: tuple[str, ...]
    env: tuple[tuple[str, str], ...]
    effort: str | None
    effort_skipped: str | None
    bypass: bool
    descriptor: dict[str, Any]
    autodetect_priority: int | None


def build_tmux_agent_catalog(
    *,
    directory: str,
    statuses: Sequence[AgentCliStatus] | None = None,
    now: float | None = None,
) -> TmuxAgentCatalog:
    """Assemble the tmux Agent catalog for launching in *directory*.

    When *statuses* is omitted (the CLI menu/launch path and ACE's worker),
    the slow plugin-derived half is served from the fingerprinted on-disk
    cache. Injected *statuses* skip the cache so tests keep driving the live
    assembler.
    """
    if statuses is None:
        payload = load_catalog_payload()
        return _catalog_from_cache(payload, directory=directory, now=now)
    return _build_catalog_from_statuses(directory=directory, statuses=statuses, now=now)


def capture_catalog_snapshot() -> CatalogCachePayload:
    """Rebuild the slow-changing catalog half from live registry and config."""
    statuses = collect_agent_cli_statuses(offline=True)
    rows, config, effort, configured = _resolved_rows(statuses, now=None)
    return CatalogCachePayload(
        fingerprint={},
        config=config,
        effort=effort,
        configured_provider=configured,
        providers=tuple(_row_to_cached(row) for row in rows),
    )


def _catalog_from_cache(
    payload: CatalogCachePayload,
    *,
    directory: str,
    now: float | None = None,
    resolve_executable_fn: ResolveExecutableFn | None = None,
    disables_fn: DisablesFn | None = None,
) -> TmuxAgentCatalog:
    """Hydrate a catalog from cached metadata plus live PATH and disable probes."""
    probe = resolve_executable_fn or _probe_executable
    disables = dict((disables_fn or get_active_provider_disables)(now))
    entries = [
        _cached_to_entry(
            item, executable=probe(item.provider, item.binary), disables=disables
        )
        for item in payload.providers
    ]
    entries.sort(key=lambda entry: (entry.key or "￿", entry.provider))
    return TmuxAgentCatalog(
        entries=tuple(entries),
        default_provider=_resolve_default_provider_from_cache(entries, payload),
        directory=directory,
    )


def _build_catalog_from_statuses(
    *,
    directory: str,
    statuses: Sequence[AgentCliStatus],
    now: float | None,
) -> TmuxAgentCatalog:
    rows, _config, _effort, _configured = _resolved_rows(statuses, now=now)
    entries = [_row_to_entry(row) for row in rows]
    entries.sort(key=lambda entry: (entry.key or "￿", entry.provider))
    return TmuxAgentCatalog(
        entries=tuple(entries),
        default_provider=_resolve_default_provider(entries),
        directory=directory,
    )


def _resolved_rows(
    statuses: Sequence[AgentCliStatus],
    *,
    now: float | None,
) -> tuple[
    list[_ResolvedProvider],
    TmuxAgentConfig,
    str | None,
    str | None,
]:
    """Resolve included providers from *statuses* plus registry and config."""
    status_by_name = {status.name: status for status in statuses}

    interactive_map = llm_registry.provider_interactive_cli_map()
    vendor_map = llm_registry.provider_vendor_map()
    color_map = llm_registry.provider_cli_status_color_map()
    hidden = llm_registry.model_picker_hidden_provider_names()
    disables = get_active_provider_disables(now)
    config = get_tmux_agent_config()
    provider_objs = cast(
        "dict[str, InvocationOptionProvider]", dict(llm_registry.iter_plugins())
    )
    default_effort = effective_default_effort_snapshot(now).effective_effort(now)
    provider_payloads = llm_registry.get_llm_metadata_payload().get("providers", {})
    configured_raw = get_llm_provider_config().get("provider")
    configured = configured_raw if isinstance(configured_raw, str) else None

    included: list[str] = []
    candidates: list[MenuKeyCandidate] = []
    for name in sorted(status_by_name):
        if name in hidden:
            continue
        descriptor = interactive_map.get(name) or {}
        if not descriptor.get("supported", True):
            continue
        provider_config = config.providers.get(name, TmuxAgentProviderConfig())
        if not provider_config.enabled:
            continue

        included.append(name)
        candidates.append(
            MenuKeyCandidate(
                provider=name,
                display_name=status_by_name[name].display_name,
                configured_key=provider_config.key,
                descriptor_key=str(descriptor.get("menu_key", "")),
            )
        )

    assigned_keys = assign_menu_keys(candidates)

    rows: list[_ResolvedProvider] = []
    for name in included:
        status = status_by_name[name]
        descriptor = interactive_map.get(name) or {}
        provider_config = config.providers.get(name, TmuxAgentProviderConfig())
        effort_level = resolve_effort_level(
            provider_effort=provider_config.effort,
            catalog_effort=config.effort,
            default_effort=default_effort,
        )
        spec = resolve_launch_argv(
            name,
            descriptor=descriptor,
            provider_config=provider_config,
            catalog_config=config,
            effort=effort_level,
            provider_obj=provider_objs.get(name),
        )
        metadata = (
            provider_payloads.get(name) if isinstance(provider_payloads, dict) else None
        )
        priority = (
            metadata.get("autodetect_priority") if isinstance(metadata, dict) else None
        )
        rows.append(
            _ResolvedProvider(
                provider=name,
                display_name=status.display_name,
                vendor=vendor_map.get(name, ""),
                color=color_map.get(name, ""),
                key=assigned_keys.get(name, ""),
                binary=status.binary,
                executable=status.executable,
                installed=status.installed,
                install_hint=status.install_hint,
                routing_disabled=disables.get(name),
                argv=spec.argv,
                env=spec.env,
                effort=spec.effort,
                effort_skipped=spec.effort_skipped,
                bypass=spec.bypass,
                descriptor=_descriptor_to_json(descriptor),
                autodetect_priority=priority if isinstance(priority, int) else None,
            )
        )
    return rows, config, default_effort, configured


def _row_to_entry(row: _ResolvedProvider) -> TmuxAgentEntry:
    return TmuxAgentEntry(
        provider=row.provider,
        display_name=row.display_name,
        vendor=row.vendor,
        color=row.color,
        key=row.key,
        binary=row.binary,
        executable=row.executable,
        installed=row.installed,
        install_hint=row.install_hint,
        routing_disabled=row.routing_disabled,
        argv=row.argv,
        env=row.env,
        effort=row.effort,
        effort_skipped=row.effort_skipped,
        bypass=row.bypass,
    )


def _row_to_cached(row: _ResolvedProvider) -> CachedProvider:
    return CachedProvider(
        provider=row.provider,
        display_name=row.display_name,
        vendor=row.vendor,
        color=row.color,
        binary=row.binary,
        descriptor=row.descriptor,
        key=row.key,
        install_hint=row.install_hint,
        autodetect_priority=row.autodetect_priority,
        argv=row.argv,
        env=row.env,
        effort=row.effort,
        effort_skipped=row.effort_skipped,
        bypass=row.bypass,
    )


def _cached_to_entry(
    item: CachedProvider,
    *,
    executable: str | None,
    disables: Mapping[str, TemporaryProviderDisable],
) -> TmuxAgentEntry:
    return TmuxAgentEntry(
        provider=item.provider,
        display_name=item.display_name,
        vendor=item.vendor,
        color=item.color,
        key=item.key,
        binary=item.binary,
        executable=executable,
        installed=executable is not None,
        install_hint=item.install_hint,
        routing_disabled=disables.get(item.provider),
        argv=item.argv,
        env=item.env,
        effort=item.effort,
        effort_skipped=item.effort_skipped,
        bypass=item.bypass,
    )


def _descriptor_to_json(descriptor: Mapping[str, Any]) -> dict[str, Any]:
    env = descriptor.get("env")
    return {
        "argv": list(descriptor.get("argv") or ()),
        "args": list(descriptor.get("args") or ()),
        "bypass_args": list(descriptor.get("bypass_args") or ()),
        "model_args": list(descriptor.get("model_args") or ()),
        "env": dict(env) if isinstance(env, Mapping) else {},
        "menu_key": str(descriptor.get("menu_key") or ""),
        "supported": descriptor.get("supported") is not False,
    }


def _probe_executable(provider: str, binary: str) -> str | None:
    path_override = os.environ.get(llm_registry.provider_path_env_var(provider))
    return resolve_executable(path_override or binary)


def _resolve_default_provider(entries: Sequence[TmuxAgentEntry]) -> str | None:
    """First of: the configured provider when installed; the highest-priority
    installed provider; the first installed entry in menu order; else None.
    """
    installed = [entry.provider for entry in entries if entry.installed]
    if not installed:
        return None

    configured = get_llm_provider_config().get("provider")
    if isinstance(configured, str) and configured in installed:
        return configured

    provider_payloads = llm_registry.get_llm_metadata_payload().get("providers", {})
    prioritized = sorted(
        (
            (priority, name)
            for name in installed
            if isinstance(provider_payloads, dict)
            and isinstance(provider_payloads.get(name), dict)
            and (priority := provider_payloads[name].get("autodetect_priority"))
            is not None
        ),
        key=lambda pair: (pair[0], pair[1]),
    )
    if prioritized:
        return prioritized[0][1]

    return installed[0]


def _resolve_default_provider_from_cache(
    entries: Sequence[TmuxAgentEntry],
    payload: CatalogCachePayload,
) -> str | None:
    installed = [entry.provider for entry in entries if entry.installed]
    if not installed:
        return None
    if payload.configured_provider in installed:
        return payload.configured_provider
    by_name = {item.provider: item for item in payload.providers}
    prioritized = sorted(
        (
            (item.autodetect_priority, item.provider)
            for name in installed
            if (item := by_name.get(name)) is not None
            and item.autodetect_priority is not None
        ),
        key=lambda pair: (pair[0], pair[1]),
    )
    if prioritized:
        return prioritized[0][1]
    return installed[0]


__all__ = [
    "build_tmux_agent_catalog",
    "capture_catalog_snapshot",
]
