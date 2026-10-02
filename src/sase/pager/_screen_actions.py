"""Label-key handling and copy/edit/follow dispatch for ``PagerScreen``.

This module is the public import path facade: the implementation lives
in the sibling ``_screen_actions_*`` modules and is re-exported here as
:class:`PagerActionMixin`.
"""

from __future__ import annotations

from sase.pager._screen_actions_labels import PagerActionLabelsMixin
from sase.pager._screen_actions_resolve import PagerActionResolveMixin
from sase.pager._screen_actions_section import PagerActionSectionMixin

__all__ = ["PagerActionMixin"]


class PagerActionMixin(
    PagerActionLabelsMixin,
    PagerActionSectionMixin,
    PagerActionResolveMixin,
):
    """Handle link labels and resolve selected targets."""
