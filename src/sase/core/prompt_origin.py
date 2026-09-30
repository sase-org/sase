"""Core-safe legacy prompt-origin heuristic for origin-less history rows.

Rows with a recorded ``origin`` never reach this classifier: the writers gate
on provenance at write time (``generated`` means "do not write"). The
heuristic exists only for the one-time cleanup of legacy rows that predate
origin recording, via ``sase prompt prune --generated --legacy``. All
matching logic lives in sase-core's ``prompt_prediction::origin`` module;
this module is a thin binding with no Python fallback.
"""

from __future__ import annotations

from sase.core.rust import require_rust_binding


def prompt_looks_generated(text: str) -> bool:
    """Return True when origin-less *text* looks machine-generated.

    Flags routine member prompts (``tribe=chop``/``tribe=job`` bindings,
    legacy ``%tribe:``/``%group:`` directives), bead-work segments, deferred
    launches, and single-turn agent headers. Hand-assigned tribes and plain
    prose stay typed.
    """
    binding = require_rust_binding("prompt_looks_generated")
    return bool(binding(text))
