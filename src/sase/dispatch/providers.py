"""Dispatch provider discovery hooks."""

from __future__ import annotations

from .provider_discovery import (
    connection_plan_for_machine,
    discover_dispatch_candidates,
    discover_dispatch_result,
)
from .provider_hooks import (
    DISPATCH_ENTRY_POINT_GROUP,
    DispatchProviderHookSpec,
    hookimpl,
    hookspec,
    iter_mapping_specs,
)
from .provider_inventory import BuiltinDispatchProviders, collect_dispatch_providers
from .provider_runtime import provider_ref_key

__all__ = [
    "DISPATCH_ENTRY_POINT_GROUP",
    "BuiltinDispatchProviders",
    "DispatchProviderHookSpec",
    "collect_dispatch_providers",
    "connection_plan_for_machine",
    "discover_dispatch_candidates",
    "discover_dispatch_result",
    "hookimpl",
    "hookspec",
    "iter_mapping_specs",
    "provider_ref_key",
]
