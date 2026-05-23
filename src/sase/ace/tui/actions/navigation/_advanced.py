"""Advanced navigation mixin facade."""

from __future__ import annotations

from ._changespec_history import ChangeSpecHistoryNavigationMixin
from ._entry_jump import EntryJumpNavigationMixin
from ._fold import FoldNavigationMixin
from ._modals import NavigationModalMixin


class AdvancedNavigationMixin(
    FoldNavigationMixin,
    EntryJumpNavigationMixin,
    NavigationModalMixin,
    ChangeSpecHistoryNavigationMixin,
):
    """Mixin providing fold mode, jump mode, help, and history navigation."""

    pass
