"""Closed, host-validated vocabularies for the shared Artifacts query profile.

Every pane-authored :class:`~sase.ace.query_profile.types.ArtifactQuerySchema`
may only select from these fixed sigil characters, predicate kinds, macro
trigger characters, and field-value kinds. A schema can point a sigil at one
of its own declared fields, or enable one of these predicate kinds, but it
can never invent new punctuation or matcher behavior. That keeps every
dialect's shorthand grammar centrally auditable instead of scattered
per-provider -- providers declare fields and facts, never executable
matchers or new punctuation.
"""

from __future__ import annotations

from dataclasses import dataclass


HOST_SIGIL_CHARS: frozenset[str] = frozenset({"+", "^", "~", "&"})
HOST_MACRO_TRIGGERS: frozenset[str] = frozenset({"%"})
HOST_FIELD_VALUE_KINDS: frozenset[str] = frozenset(
    {"string", "enum", "bool", "date", "int"}
)
HOST_ANY_SPECIAL_SIGIL = "*"


@dataclass(frozen=True, slots=True)
class HostPredicateDef:
    """One host-owned zero-argument predicate kind and its fixed sigils."""

    name: str
    triple_sigil: str
    short_sigil: str
    negation_sigil: str
    label: str


HOST_PREDICATES: dict[str, HostPredicateDef] = {
    definition.name: definition
    for definition in (
        HostPredicateDef("error_suffix", "!!!", "!", "!!", "has an error suffix"),
        HostPredicateDef("running_agent", "@@@", "@", "!@", "has a running agent"),
        HostPredicateDef("running_process", "$$$", "$", "!$", "has a running process"),
    )
}

__all__ = [
    "HOST_ANY_SPECIAL_SIGIL",
    "HOST_FIELD_VALUE_KINDS",
    "HOST_MACRO_TRIGGERS",
    "HOST_PREDICATES",
    "HOST_SIGIL_CHARS",
    "HostPredicateDef",
]
