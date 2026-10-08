"""Durable human-authorship provenance for agent launches.

Every agent's ``agent_meta.json`` records ``prompt_origin`` (``typed``,
``generated``, or ``unknown``) and ``prompt_source_surface``. The values
travel from the launch ingress to the child runner through the environment:
launch funnels that know the classification stamp it into the child's
``extra_env``; :func:`sase.agent.launch_spawn.spawn_agent_subprocess`
fills any gap fail-closed; the runner persists whatever it finds.

The classification itself is never invented here. Launch funnels reuse
:func:`sase.history.prompt_store_mutations.effective_prompt_origin`, so
history and ``agent_meta.json`` can never disagree about one launch.
"""

from __future__ import annotations

import os
from collections.abc import Mapping, Sequence
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sase.history.prompt_store import PromptOrigin

#: Child environment key carrying the launch's human-authorship origin.
PROMPT_ORIGIN_ENV = "SASE_PROMPT_ORIGIN"

#: Child environment key carrying the surface that submitted the launch
#: (``ace``, ``cli``, ``bead_work``, ...). Best-effort context for future
#: readers; ``unknown`` when the funnel does not know.
PROMPT_SOURCE_SURFACE_ENV = "SASE_PROMPT_SOURCE_SURFACE"

#: The only values ``prompt_origin`` may hold in ``agent_meta.json``.
PROMPT_ORIGINS = ("typed", "generated", "unknown")

_UNKNOWN = "unknown"


def normalize_prompt_origin(value: object) -> str:
    """Return *value* when it is a known origin, else ``"unknown"``."""
    if isinstance(value, str) and value in PROMPT_ORIGINS:
        return value
    return _UNKNOWN


def normalize_prompt_source_surface(value: object) -> str:
    """Return the surface string, or ``"unknown"`` when absent/blank."""
    if isinstance(value, str) and value.strip():
        return value.strip()
    return _UNKNOWN


def _prompt_origin_for_launch(
    origin: PromptOrigin | None,
    *,
    launch_envs: tuple[Mapping[str, str] | None, ...] = (),
) -> str:
    """Resolve one launch's durable origin, failing closed.

    A valid stamp already present on any of *launch_envs* (placed by an
    outer launch funnel, e.g. repeat-slot recursion inheriting its
    parent's stamp) is kept verbatim. Otherwise the shared history
    classification decides, with ``None`` (unknown/legacy path) mapping
    to ``"unknown"``.
    """
    for env in launch_envs:
        if not env:
            continue
        stamped = env.get(PROMPT_ORIGIN_ENV)
        if isinstance(stamped, str) and stamped in PROMPT_ORIGINS:
            return stamped
    from sase.history.prompt_store_mutations import effective_prompt_origin

    effective = effective_prompt_origin(origin, launch_envs=launch_envs)
    if effective is None:
        return _UNKNOWN
    return normalize_prompt_origin(effective)


def with_launch_provenance(
    extra_env: dict[str, str] | None,
    *,
    origin: PromptOrigin | None,
    source_surface: str | None = None,
    launch_envs: tuple[Mapping[str, str] | None, ...] = (),
) -> dict[str, str]:
    """Return a copy of *extra_env* stamped with this launch's provenance.

    The stamp is sticky: when *extra_env* (or any of *launch_envs*)
    already carries a valid origin, that value is kept and only a
    missing surface is filled. The input mapping is never mutated.
    """
    resolved_origin = _prompt_origin_for_launch(
        origin, launch_envs=(extra_env, *launch_envs)
    )
    stamped = dict(extra_env or {})
    stamped.setdefault(PROMPT_ORIGIN_ENV, resolved_origin)
    # An explicitly known surface wins over an absent one, but never
    # overwrites a stamp an outer funnel already placed.
    if source_surface and stamped.get(PROMPT_SOURCE_SURFACE_ENV) in (None, _UNKNOWN):
        stamped[PROMPT_SOURCE_SURFACE_ENV] = normalize_prompt_source_surface(
            source_surface
        )
    stamped.setdefault(PROMPT_SOURCE_SURFACE_ENV, _UNKNOWN)
    return stamped


def fill_launch_provenance_default(
    extra_env: dict[str, str] | None,
    *,
    env: Mapping[str, str] | None = None,
) -> dict[str, str]:
    """Fill missing provenance keys fail-closed for a direct spawn.

    Launch paths that never passed through a classifying funnel (retry
    continuations, monitor follow-ups, admission-engine dispatches) inherit
    a valid ambient stamp when one is present — a retry continues its own
    run — and otherwise record ``"generated"``/``"unknown"``. An explicit
    stamp is never overwritten.
    """
    stamped = dict(extra_env or {})
    ambient = os.environ if env is None else env
    if stamped.get(PROMPT_ORIGIN_ENV) not in PROMPT_ORIGINS:
        ambient_origin = ambient.get(PROMPT_ORIGIN_ENV)
        if isinstance(ambient_origin, str) and ambient_origin in PROMPT_ORIGINS:
            stamped[PROMPT_ORIGIN_ENV] = ambient_origin
        else:
            stamped[PROMPT_ORIGIN_ENV] = "generated"
    if not stamped.get(PROMPT_SOURCE_SURFACE_ENV):
        ambient_surface = ambient.get(PROMPT_SOURCE_SURFACE_ENV)
        stamped[PROMPT_SOURCE_SURFACE_ENV] = normalize_prompt_source_surface(
            ambient_surface
        )
    return stamped


def read_launch_provenance(
    env: Mapping[str, str] | None = None,
) -> tuple[str, str]:
    """Return the ``(origin, surface)`` pair a runner persists to metadata.

    Missing keys read as ``"unknown"`` (legacy launches); anything outside
    the known origin set also reads as ``"unknown"``.
    """
    ambient = os.environ if env is None else env
    return (
        normalize_prompt_origin(ambient.get(PROMPT_ORIGIN_ENV)),
        normalize_prompt_source_surface(ambient.get(PROMPT_SOURCE_SURFACE_ENV)),
    )


def stamp_segment_provenance(
    segment_extra_env: Sequence[dict[str, str] | None] | None,
    *,
    origin: PromptOrigin | None,
    source_surface: str | None = None,
) -> list[dict[str, str] | None] | None:
    """Stamp every per-segment env, preserving ``None`` slots and length."""
    if segment_extra_env is None:
        return None
    return [
        with_launch_provenance(
            dict(entry) if entry is not None else None,
            origin=origin,
            source_surface=source_surface,
        )
        for entry in segment_extra_env
    ]


__all__ = [
    "PROMPT_ORIGINS",
    "PROMPT_ORIGIN_ENV",
    "PROMPT_SOURCE_SURFACE_ENV",
    "fill_launch_provenance_default",
    "normalize_prompt_origin",
    "normalize_prompt_source_surface",
    "read_launch_provenance",
    "stamp_segment_provenance",
    "with_launch_provenance",
]
