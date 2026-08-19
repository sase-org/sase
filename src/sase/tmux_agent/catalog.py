"""Assemble the tmux Agent catalog from registry, config, and detection state."""

from __future__ import annotations

from collections.abc import Sequence
from typing import cast

from sase.agent_clis.models import AgentCliStatus
from sase.agent_clis.operations import collect_agent_cli_statuses
from sase.config.tmux_agent import TmuxAgentProviderConfig, get_tmux_agent_config
from sase.llm_provider import (
    effective_default_effort_snapshot,
    get_active_provider_disables,
)
from sase.llm_provider import registry as llm_registry
from sase.llm_provider.config import get_llm_provider_config

from .keys import MenuKeyCandidate, assign_menu_keys
from .launch_spec import (
    InvocationOptionProvider,
    resolve_effort_level,
    resolve_launch_argv,
)
from .models import TmuxAgentCatalog, TmuxAgentEntry


def build_tmux_agent_catalog(
    *,
    directory: str,
    statuses: Sequence[AgentCliStatus] | None = None,
    now: float | None = None,
) -> TmuxAgentCatalog:
    """Assemble the tmux Agent catalog for launching in *directory*.

    Excludes providers hidden from model pickers, providers whose interactive
    descriptor sets ``supported: False``, and providers disabled through
    ``tmux_agent.providers.<name>.enabled``. Providers that declare no CLI name
    never reach *statuses* in the first place (``collect_agent_cli_statuses``
    already skips them), so no separate check is needed here.
    """
    resolved_statuses = (
        collect_agent_cli_statuses(offline=True) if statuses is None else statuses
    )
    status_by_name = {status.name: status for status in resolved_statuses}

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

    entries: list[TmuxAgentEntry] = []
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
        entries.append(
            TmuxAgentEntry(
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
            )
        )

    entries.sort(key=lambda entry: (entry.key or "￿", entry.provider))

    return TmuxAgentCatalog(
        entries=tuple(entries),
        default_provider=_resolve_default_provider(entries),
        directory=directory,
    )


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


__all__ = [
    "build_tmux_agent_catalog",
]
