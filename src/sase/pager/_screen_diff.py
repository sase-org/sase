"""Read/diff view toggle, change navigation, and fold expansion.

Owns the ``=`` view toggle, ``[``/``]`` change jumps in both views,
in-place fold expansion through jump labels, and the ``yy`` unified-diff
copy branch for ``PagerScreen`` history sections. Version-step, discovery,
and gutter-mark logic stays in ``_screen_history``; word-diff rendering
stays in ``pager.history.diff``.

This module is the public import path facade: the implementation lives
in the sibling ``_screen_diff_*`` modules and is re-exported here as
:class:`PagerDiffMixin`.
"""

from __future__ import annotations

from sase.pager._screen_diff_folds import PagerDiffFoldsMixin
from sase.pager._screen_diff_navigate import PagerDiffNavigateMixin
from sase.pager._screen_diff_view import PagerDiffViewMixin

__all__ = ["PagerDiffMixin"]


class PagerDiffMixin(
    PagerDiffViewMixin,
    PagerDiffNavigateMixin,
    PagerDiffFoldsMixin,
):
    """Own the history diff view and change navigation for one screen."""
