"""Canonical reasoning-effort vocabulary shared across the xprompt layer.

Defines the single source of truth for reasoning-effort level spelling plus
:func:`split_model_effort`, the helper that peels a trailing ``@<level>`` token
off a model string. The directive parser and the fan-out naming logic both use
these; later epic phases reuse the same constant for the ``default_effort``
config field (Phase 2), provider CLI translation (Phase 3), and the mirrored
Rust core grammar (Phase 5).

The public surface spells it ``effort``; the threaded/stored field is named
``reasoning_effort`` everywhere else. Spelling is validated globally against
this vocabulary — *which* levels a given provider actually honors is decided in
the provider adapter, not here.
"""

from __future__ import annotations

# Canonical vocabulary, ordered from least to most effort for human-readable
# error messages. Membership checks use the frozenset below.
EFFORT_LEVELS_ORDERED: tuple[str, ...] = (
    "none",
    "minimal",
    "low",
    "medium",
    "high",
    "xhigh",
    "max",
)

# The canonical effort-level constant referenced throughout the epic.
EFFORT_LEVELS: frozenset[str] = frozenset(EFFORT_LEVELS_ORDERED)


def is_valid_effort(level: str) -> bool:
    """Return True when *level* is a canonical reasoning-effort level."""
    return level in EFFORT_LEVELS


def split_model_effort(model: str) -> tuple[str, str | None]:
    """Split a trailing ``@<effort>`` token off a model string.

    Only a trailing ``@<level>`` whose ``<level>`` is a known effort level is
    split off; any other ``@`` — or an unknown trailing token — is left in
    place so model ids that legitimately contain ``@`` survive untouched.

    Returns ``(clean_model, effort)`` where ``effort`` is ``None`` when no
    known-effort suffix is present.

    Callers must bypass this split for backtick-literal model values
    (``%model:`literal@id` ``), which intentionally preserve ``@``.
    """
    at = model.rfind("@")
    if at <= 0:
        return model, None
    candidate = model[at + 1 :]
    if candidate in EFFORT_LEVELS:
        return model[:at], candidate
    return model, None
