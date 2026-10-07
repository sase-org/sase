"""Bundle section assembly: package split, units, overlays, and layout.

This module owns the section-level composition (E2 decisions 5-7): splitting
the inlined contract template into package sections, turning memory units
into home/project sections, applying lifecycle overlays and shadowing, and
ordering the bundle layout. Only its miss-path helpers import the heavy
composition modules; the cache-hit path never reaches this module.

Facade preserving the original public import path; the implementation now
lives in :mod:`sase.instructions.sections_base`,
:mod:`sase.instructions.sections_package`,
:mod:`sase.instructions.sections_units`, and
:mod:`sase.instructions.sections_assemble`, with helpers shared by more
than one of those modules as public names in the already-private
:mod:`sase.instructions._sections_shared`.
"""

from __future__ import annotations

from sase.instructions._sections_shared import InstructionCompileError
from sase.instructions.sections_assemble import assemble_sections
from sase.instructions.sections_base import (
    DEFAULT_FRAME_TITLE,
    GENERATED_CONTRACT_RELATIVE_PATH,
    HELPER_TEMPLATE_SOURCE_PATH,
    PACKAGED_TEMPLATE_SOURCE_PATH,
    SectionBuilder,
    section_slug,
    section_wire_dict,
    tokens_estimate,
)

__all__ = [
    "DEFAULT_FRAME_TITLE",
    "GENERATED_CONTRACT_RELATIVE_PATH",
    "HELPER_TEMPLATE_SOURCE_PATH",
    "InstructionCompileError",
    "PACKAGED_TEMPLATE_SOURCE_PATH",
    "SectionBuilder",
    "assemble_sections",
    "section_slug",
    "section_wire_dict",
    "tokens_estimate",
]
