"""Guard the xprompt-to-macro rename outside the TUI.

This module preserves the original public test import path; implementations live in
private modules grouped by the content they scan.
"""

from __future__ import annotations

import pytest

from tests._macro_terminology_docs import (
    test_macro_docs_allowlist_is_classified,
    test_macro_docs_and_memory_avoid_xprompt_terms,
    test_macro_docs_paths_avoid_xprompt_components,
)
from tests._macro_terminology_identifiers import (
    test_macro_imports_avoid_xprompt_modules,
    test_macro_paths_avoid_xprompt_components,
    test_macro_source_avoids_xprompt_identifiers,
)
from tests._macro_terminology_strings import (
    test_macro_comments_avoid_xprompt_terms,
    test_macro_resources_avoid_xprompt_terms,
    test_macro_string_allowlist_is_classified,
    test_macro_string_literals_avoid_xprompt_terms,
)

pytestmark = pytest.mark.contract

__all__ = (
    "test_macro_docs_allowlist_is_classified",
    "test_macro_docs_and_memory_avoid_xprompt_terms",
    "test_macro_docs_paths_avoid_xprompt_components",
    "test_macro_imports_avoid_xprompt_modules",
    "test_macro_paths_avoid_xprompt_components",
    "test_macro_source_avoids_xprompt_identifiers",
    "test_macro_comments_avoid_xprompt_terms",
    "test_macro_resources_avoid_xprompt_terms",
    "test_macro_string_allowlist_is_classified",
    "test_macro_string_literals_avoid_xprompt_terms",
)
