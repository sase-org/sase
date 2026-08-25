"""Concrete :class:`ArtifactQuerySchema` definitions for every Artifacts pane.

Each built-in constructor below is a Python-authored description of a
dialect that already exists in the codebase, hand-checked against its real
source of truth (the Patch tokenizer's property/shorthand tables for
Patches, and each flat pane's ``filter_query`` module for Stitches, Beads,
Plans, and Files) so the compiled profile preserves that dialect's current
canonical behavior byte-for-byte. :func:`provider_query_schema` instead
*derives* a schema generically from a document provider's declared
``ref.properties``, proving the profile shape needs no per-provider Python.

This package intentionally imports only pure domain/backend constants (never
Textual widgets) to stay usable from non-TUI consumers such as the Rust
binding and CLI explainability surfaces. Each pane's dialect lives in its
own module (``_patches``, ``_stitches``, etc.); this file only re-exports
the public schema constructors.
"""

from __future__ import annotations

from ._agents import agents_query_schema
from ._beads import beads_query_schema
from ._files import files_query_schema
from ._patches import patches_query_schema
from ._plans import plans_query_schema
from ._procs import procs_query_schema
from ._provider import provider_query_schema
from ._stitches import stitches_query_schema

__all__ = [
    "agents_query_schema",
    "beads_query_schema",
    "files_query_schema",
    "patches_query_schema",
    "plans_query_schema",
    "procs_query_schema",
    "provider_query_schema",
    "stitches_query_schema",
]
