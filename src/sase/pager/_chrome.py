"""Pure rendering helpers for the pager's sticky chrome and footer.

No Textual imports here: everything is a plain function from document/section
state to a Rich :class:`~rich.text.Text`, so the shapes are unit-testable
without booting an App.

This module preserves the public import surface while the implementation is
split by chrome responsibility across sibling modules.
"""

from __future__ import annotations

from sase.pager._chrome_footer import footer_legend
from sase.pager._chrome_goto import goto_command_line
from sase.pager._chrome_history import time_verbs_for_moment
from sase.pager._chrome_sections import section_accent, section_rule
from sase.pager._chrome_subject import subject_line, subject_parts

__all__ = [
    "footer_legend",
    "goto_command_line",
    "section_rule",
    "section_accent",
    "subject_line",
    "subject_parts",
    "time_verbs_for_moment",
]
