"""Shared, profile-parameterized query schema for every Artifacts pane.

An :class:`~sase.ace.query_profile.types.ArtifactQuerySchema` is authored
once per pane dialect (see :mod:`sase.ace.query_profile.profiles`) and
compiled by :func:`~sase.ace.query_profile.compiler.compile_query_profile`
into an immutable, digest-stable
:class:`~sase.ace.query_profile.compiler.CompiledQueryProfile`. Sigils,
zero-argument predicates, and macro triggers may only be selected from the
closed host vocabularies in :mod:`sase.ace.query_profile.registry` -- a
schema can never invent new punctuation or matcher behavior.

``ArtifactsPaneContract`` (:mod:`sase.ace.tui._artifact_tab_model`) compiles
one of these profiles per pane and carries it as ``query_profile``; the
shared ``FilterBar`` (:mod:`sase.ace.tui.widgets.filter_bar`) configures its
dialect from that profile, and
:mod:`sase.core.query_profile_corpus_facade` routes production evaluation
through the Rust corpus/query handles it describes.

Import order note: ``.types`` and ``.registry`` (no cross-package imports)
must be imported before ``.profiles``/``.pane_registry``, which reach into
:mod:`sase.ace.query` and would otherwise observe this package
mid-initialization and fail to import ``QueryFieldSpec`` -- that module
imports back from here (:mod:`sase.ace.query.profile_evaluator`).
"""

from __future__ import annotations

from .registry import (
    HOST_ANY_SPECIAL_SIGIL,
    HOST_DATE_BOUND_KEYS,
    HOST_DURATION_BOUND_KEYS,
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
from .compiler import CompiledQueryProfile, QueryProfileError, compile_query_profile
from .pane_registry import compiled_profile_for_builtin_pane
from .profiles import (
    agents_query_schema,
    beads_query_schema,
    files_query_schema,
    patches_query_schema,
    plans_query_schema,
    procs_query_schema,
    provider_query_schema,
    stitches_query_schema,
)

__all__ = [
    "HOST_ANY_SPECIAL_SIGIL",
    "HOST_DATE_BOUND_KEYS",
    "HOST_DURATION_BOUND_KEYS",
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
    "agents_query_schema",
    "beads_query_schema",
    "compile_query_profile",
    "compiled_profile_for_builtin_pane",
    "files_query_schema",
    "patches_query_schema",
    "plans_query_schema",
    "procs_query_schema",
    "provider_query_schema",
    "stitches_query_schema",
]
