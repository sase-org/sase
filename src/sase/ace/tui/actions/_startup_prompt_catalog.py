"""Prompt catalog and snippet-cache helpers for ACE startup.

``StartupPromptCatalogMixin`` is the public mixin imported by ``startup.py``. Its
implementation is split across focused private mixins so this module stays
as a small composition point.
"""

from __future__ import annotations

from ._startup_prompt_catalog_core import StartupPromptCatalogCoreMixin
from ._startup_prompt_catalog_semantics import StartupPromptCatalogSemanticsMixin


class StartupPromptCatalogMixin(
    StartupPromptCatalogCoreMixin,
    StartupPromptCatalogSemanticsMixin,
):
    """Mixin for memory-only prompt catalog and snippet state."""
