"""Python-authored input types for the shared Artifacts query profile.

An :class:`ArtifactQuerySchema` is hand-authored once per Artifacts pane
dialect (Patches, Stitches, Beads, Plans, Files, or a document provider) and
fed to :func:`sase.ace.query_profile.compiler.compile_query_profile`, which
validates it against the closed host vocabularies in
:mod:`sase.ace.query_profile.registry` and produces an immutable, digested
:class:`~sase.ace.query_profile.compiler.CompiledQueryProfile`.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

FieldValueKind = Literal["string", "enum", "bool", "date", "int"]


@dataclass(frozen=True, slots=True)
class QueryFieldSpec:
    """One field a pane's query dialect knows about.

    ``filterable`` and ``searchable`` are independent: a field can be
    addressable via ``key:value`` syntax only (``filterable=True,
    searchable=False``), contribute to free-text search only (Patch's
    ``description``, for example: ``filterable=False, searchable=True``), or
    both. ``repeatable`` and ``negatable`` only apply to filterable fields.

    ``exact_match`` only applies to ``string``-kind fields: ``True`` requires
    a ``key:value`` term to equal a row's value exactly (case-insensitively);
    ``False`` (the default) matches by substring. ``enum``-kind fields are
    always exact regardless of this flag; ``bool``/``int``/``date`` fields
    have their own typed comparison and ignore it too.
    """

    key: str
    value_kind: FieldValueKind = "string"
    filterable: bool = True
    searchable: bool = False
    repeatable: bool = False
    negatable: bool = False
    exact_match: bool = False
    static_values: tuple[str, ...] = ()
    hint: str = ""


@dataclass(frozen=True, slots=True)
class QuerySigilSpec:
    """A single-punctuation shorthand for ``field:value``.

    ``sigil`` must be one of
    :data:`sase.ace.query_profile.registry.HOST_SIGIL_CHARS`.
    """

    sigil: str
    field: str


@dataclass(frozen=True, slots=True)
class QueryMacroSpec:
    """A ``<trigger><letter>`` shorthand for a fixed ``field:value`` pair.

    ``trigger`` must be one of
    :data:`sase.ace.query_profile.registry.HOST_MACRO_TRIGGERS`.
    """

    trigger: str
    letter: str
    field: str
    value: str


@dataclass(frozen=True, slots=True)
class ArtifactQuerySchema:
    """Python-authored description of one Artifacts pane's query dialect.

    ``predicates`` selects zero-argument predicate kinds by name from
    :data:`sase.ace.query_profile.registry.HOST_PREDICATES`; their sigils and
    matching behavior are host-owned, not schema-authored. ``any_special``
    enables the ``*`` "any predicate matches" shorthand and is only valid
    when every host predicate kind is declared.
    """

    pane_id: str
    boolean: bool
    fields: tuple[QueryFieldSpec, ...]
    sigils: tuple[QuerySigilSpec, ...] = ()
    predicates: tuple[str, ...] = ()
    any_special: bool = False
    macros: tuple[QueryMacroSpec, ...] = ()
    free_text_hint: str = ""


__all__ = [
    "ArtifactQuerySchema",
    "FieldValueKind",
    "QueryFieldSpec",
    "QueryMacroSpec",
    "QuerySigilSpec",
]
