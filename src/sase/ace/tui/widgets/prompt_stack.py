"""Public prompt-stack state API.

The implementation is split by responsibility across private sibling modules:
canonical prompt parsing, source target metadata, binding persistence, and the
pure editing state model.  This facade preserves the original import surface
for the TUI and its tests.
"""

from __future__ import annotations

from ._prompt_stack_parsing import split_frontmatter, split_prompt_text
from ._prompt_stack_state import PromptStackItem, PromptStackState
from ._prompt_stack_targets import (
    SnippetPaneTarget,
    SourceFingerprint,
    XPromptBinding,
    XPromptReadonlyTarget,
)

__all__ = [
    "PromptStackItem",
    "PromptStackState",
    "SnippetPaneTarget",
    "SourceFingerprint",
    "XPromptBinding",
    "XPromptReadonlyTarget",
    "split_frontmatter",
    "split_prompt_text",
]
