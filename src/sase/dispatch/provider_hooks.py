"""Hook specifications for remote dispatch providers."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

import pluggy

DISPATCH_ENTRY_POINT_GROUP = "sase_dispatch"

hookspec = pluggy.HookspecMarker("sase_dispatch")
hookimpl = pluggy.HookimplMarker("sase_dispatch")


class DispatchProviderHookSpec:
    """Hook specifications for remote dispatch providers."""

    @hookspec
    def dispatch_provider_specs(
        self,
    ) -> Iterable[Mapping[str, Any]] | Mapping[str, Any] | None:
        """Return remote dispatch provider specs."""
        ...

    @hookspec
    def dispatch_discover(
        self,
        # Hook argument names and kinds are a cross-repo compatibility
        # boundary: pluggy invokes hookimpls positionally, so these must stay
        # positional-or-keyword without defaults.
        provider_ref: str,
        config: Mapping[str, Any],
        timeout_seconds: float,
    ) -> Iterable[Mapping[str, Any]] | Mapping[str, Any] | None:
        """Return explicit remote machine discovery candidates."""
        ...

    @hookspec
    def dispatch_connection_plan(
        self,
        # Hook argument names and kinds are a cross-repo compatibility
        # boundary: pluggy invokes hookimpls positionally, so these must stay
        # positional-or-keyword without defaults.
        provider_ref: str,
        machine: Mapping[str, Any],
        config: Mapping[str, Any],
        timeout_seconds: float,
    ) -> Mapping[str, Any] | None:
        """Return a serializable fleet connection plan for one machine."""
        ...


def iter_mapping_specs(value: object) -> tuple[Mapping[str, Any], ...]:
    if value is None:
        return ()
    if isinstance(value, Mapping):
        return (value,)
    if isinstance(value, Iterable) and not isinstance(value, (str, bytes, bytearray)):
        return tuple(item for item in value if isinstance(item, Mapping))
    return ()


__all__ = [
    "DISPATCH_ENTRY_POINT_GROUP",
    "DispatchProviderHookSpec",
    "hookimpl",
    "hookspec",
    "iter_mapping_specs",
]
