"""Advanced navigation mixin facade."""

from __future__ import annotations

from ._entry_jump import EntryJumpNavigationMixin
from ._fold import FoldNavigationMixin
from ._member_jump import MemberJumpNavigationMixin
from ._modals import NavigationModalMixin
from ._node_jump import NodeJumpNavigationMixin


class AdvancedNavigationMixin(
    FoldNavigationMixin,
    NodeJumpNavigationMixin,
    MemberJumpNavigationMixin,
    EntryJumpNavigationMixin,
    NavigationModalMixin,
):
    """Mixin providing fold mode, jump mode, help, and history navigation."""

    pass
