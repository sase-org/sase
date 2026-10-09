"""Raw directive match collection for prompt directive extraction.

Compatibility facade: the implementation lives in the sibling
``_directive_collect_*`` modules. This module re-exports the public entry
points so existing import paths keep working.
"""

from __future__ import annotations

from ._directive_collect_main import (
    collect_prompt_directive_matches as collect_prompt_directive_matches,
)
from ._directive_collect_occurrences import (
    collect_queue_directive_occurrences as collect_queue_directive_occurrences,
)
from ._exceptions import DirectiveError as DirectiveError

__all__ = [
    "DirectiveError",
    "collect_prompt_directive_matches",
    "collect_queue_directive_occurrences",
]
