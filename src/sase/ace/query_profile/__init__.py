"""Shared, profile-parameterized query schema for every Artifacts pane.

An :class:`~sase.ace.query_profile.types.ArtifactQuerySchema` is authored
once per pane dialect (see :mod:`sase.ace.query_profile.profiles`) and
compiled by :func:`~sase.ace.query_profile.compiler.compile_query_profile`
into an immutable, digest-stable
:class:`~sase.ace.query_profile.compiler.CompiledQueryProfile`. Sigils,
zero-argument predicates, and macro triggers may only be selected from the
closed host vocabularies in :mod:`sase.ace.query_profile.registry` -- a
schema can never invent new punctuation or matcher behavior.

This package defines the schema and its compiler only. Wiring the compiled
profile into live pane filtering, the Rust parser/corpus, and the Python
reference evaluator is the responsibility of later phases of the
``sase-m6.6.1`` epic.
"""

from __future__ import annotations

from .compiler import CompiledQueryProfile, QueryProfileError, compile_query_profile
from .profiles import (
    beads_query_schema,
    files_query_schema,
    patches_query_schema,
    plans_query_schema,
    provider_query_schema,
    stitches_query_schema,
)
from .registry import (
    HOST_ANY_SPECIAL_SIGIL,
    HOST_FIELD_VALUE_KINDS,
    HOST_MACRO_TRIGGERS,
    HOST_PREDICATES,
    HOST_SIGIL_CHARS,
    HostPredicateDef,
)
from .types import (
    ArtifactQuerySchema,
    FieldValueKind,
    QueryFieldSpec,
    QueryMacroSpec,
    QuerySigilSpec,
)

__all__ = [
    "HOST_ANY_SPECIAL_SIGIL",
    "HOST_FIELD_VALUE_KINDS",
    "HOST_MACRO_TRIGGERS",
    "HOST_PREDICATES",
    "HOST_SIGIL_CHARS",
    "ArtifactQuerySchema",
    "CompiledQueryProfile",
    "FieldValueKind",
    "HostPredicateDef",
    "QueryFieldSpec",
    "QueryMacroSpec",
    "QueryProfileError",
    "QuerySigilSpec",
    "beads_query_schema",
    "compile_query_profile",
    "files_query_schema",
    "patches_query_schema",
    "plans_query_schema",
    "provider_query_schema",
    "stitches_query_schema",
]
