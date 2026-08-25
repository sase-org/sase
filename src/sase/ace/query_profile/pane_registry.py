"""Pane-id lookup for compiled query profiles.

Persistence and other consumers that only have a pane id string (not a
live provider spec) use this to resolve the current
:class:`~sase.ace.query_profile.compiler.CompiledQueryProfile` for a
built-in pane, e.g. to stamp or validate a saved record's profile digest.
"""

from __future__ import annotations

from collections.abc import Callable

from .compiler import CompiledQueryProfile, compile_query_profile
from .profiles import (
    agents_query_schema,
    beads_query_schema,
    files_query_schema,
    patches_query_schema,
    plans_query_schema,
    procs_query_schema,
    stitches_query_schema,
)
from .types import ArtifactQuerySchema

_BUILTIN_SCHEMA_BUILDERS: dict[str, Callable[[], ArtifactQuerySchema]] = {
    "patches": patches_query_schema,
    "stitches": stitches_query_schema,
    "beads": beads_query_schema,
    "ref:plan": plans_query_schema,
    "agents": agents_query_schema,
    "files": files_query_schema,
    "procs": procs_query_schema,
}


def compiled_profile_for_builtin_pane(pane_id: str) -> CompiledQueryProfile | None:
    """Return the compiled profile for a built-in pane, or ``None``.

    Document-provider panes (``ref:<kind>`` other than ``ref:plan``) need a
    live ``ref.properties`` spec to compile a profile (see
    :func:`sase.ace.query_profile.profiles.provider_query_schema`), which
    isn't available from a bare pane id. Callers treat ``None`` as "no
    digest known yet" rather than an error -- wiring live profile
    resolution for those panes into persistence is later epic work.
    """
    builder = _BUILTIN_SCHEMA_BUILDERS.get(pane_id)
    if builder is None:
        return None
    return compile_query_profile(builder())


__all__ = ["compiled_profile_for_builtin_pane"]
