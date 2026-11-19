"""Pane-id lookup for compiled query profiles.

Persistence and other consumers that only have a pane id string (not a
live provider spec) use this to resolve the current
:class:`~sase.ace.query_profile.compiler.CompiledQueryProfile` for a
built-in pane, e.g. to stamp or validate a saved record's profile digest.
"""

from __future__ import annotations

from importlib import import_module

from .compiler import CompiledQueryProfile, compile_query_profile
from .types import ArtifactQuerySchema

_BUILTIN_SCHEMA_BUILDERS: dict[str, tuple[str, str]] = {
    "patches": (".profiles._patches", "patches_query_schema"),
    "stitches": (".profiles._stitches", "stitches_query_schema"),
    "beads": (".profiles._beads", "beads_query_schema"),
    "ref:plan": (".profiles._plans", "plans_query_schema"),
    "agents": (".profiles._agents", "agents_query_schema"),
    "agents-live": (".profiles._agents_live", "agents_live_query_schema"),
    "agents-archive": (".profiles._agents_archive", "agents_archive_query_schema"),
    "files": (".profiles._files", "files_query_schema"),
    "procs": (".profiles._procs", "procs_query_schema"),
}

# Memoized built-in profiles, keyed by pane id. The zero-argument schema
# builders above are static module code, so the pane id alone determines
# the compiled output within a process: no input can change under a cached
# entry. ``CompiledQueryProfile`` and its field specs are frozen
# dataclasses of tuples, so sharing one instance across panes, ticks, and
# keystrokes is safe. Unknown pane ids resolve to ``None`` on every call
# and are deliberately not cached, so a later-registered builder is
# picked up without an explicit clear.
_COMPILED_BUILTIN_PANE_CACHE: dict[str, CompiledQueryProfile] = {}


def compiled_profile_for_builtin_pane(pane_id: str) -> CompiledQueryProfile | None:
    """Return the compiled profile for a built-in pane, or ``None``.

    Document-provider panes (``ref:<kind>`` other than ``ref:plan``) need a
    live ``ref.properties`` spec to compile a profile (see
    :func:`sase.ace.query_profile.profiles.provider_query_schema`), which
    isn't available from a bare pane id. Callers treat ``None`` as "no
    digest known yet" rather than an error -- wiring live profile
    resolution for those panes into persistence is later epic work.
    """
    try:
        return _COMPILED_BUILTIN_PANE_CACHE[pane_id]
    except KeyError:
        pass
    builder_ref = _BUILTIN_SCHEMA_BUILDERS.get(pane_id)
    if builder_ref is None:
        return None
    module_name, attr = builder_ref
    module = import_module(module_name, __package__)
    builder = getattr(module, attr)
    profile = compile_query_profile(builder())
    _COMPILED_BUILTIN_PANE_CACHE[pane_id] = profile
    return profile


def clear_compiled_builtin_pane_cache() -> None:
    """Drop all memoized built-in profiles (tests only).

    Production builders are static, so the cache never goes stale on its
    own; this exists for tests that register or replace builders.
    """
    _COMPILED_BUILTIN_PANE_CACHE.clear()


__all__ = ["clear_compiled_builtin_pane_cache", "compiled_profile_for_builtin_pane"]
