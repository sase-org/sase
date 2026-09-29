"""Tests for prompt input snippet expansion.

Split facade: the tests now live in
``test_prompt_snippet_expansion_basic``,
``test_prompt_snippet_expansion_nesting``,
``test_prompt_snippet_expansion_tabstops``, and
``test_prompt_snippet_expansion_project`` (shared helpers in
``_prompt_snippet_expansion_shared``). This module re-exports the public names
so the original import path keeps working. It collects no tests itself.
"""

from __future__ import annotations

from tests.ace.tui.widgets._prompt_snippet_expansion_shared import (
    SnippetTestApp,
    setup_snippet_expansion,
)
from tests.ace.tui.widgets.test_prompt_snippet_expansion_basic import (
    TestBasicExpansion,
    TestMultiLineExpansion,
    TestMultiLineIndentation,
    TestNoExpansion,
    TestTriggerInContext,
)
from tests.ace.tui.widgets.test_prompt_snippet_expansion_nesting import (
    TestNestedSessions,
    TestSnippetPriority,
)
from tests.ace.tui.widgets.test_prompt_snippet_expansion_project import (
    TestSnippetProjectVariable,
)
from tests.ace.tui.widgets.test_prompt_snippet_expansion_tabstops import (
    TestBackwardTabstopNavigation,
    TestTabstopExpansion,
)

__test__ = False

__all__ = [
    "SnippetTestApp",
    "TestBackwardTabstopNavigation",
    "TestBasicExpansion",
    "TestMultiLineExpansion",
    "TestMultiLineIndentation",
    "TestNestedSessions",
    "TestNoExpansion",
    "TestSnippetPriority",
    "TestSnippetProjectVariable",
    "TestTabstopExpansion",
    "TestTriggerInContext",
    "setup_snippet_expansion",
]
