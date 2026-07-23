"""Public loader mixin and compatibility imports for the AXE display."""

from ._loader_items import (
    axe_item_key as _axe_item_key,
    find_axe_item_idx,
    selected_axe_item_key,
)
from ._loader_refresh import AxeDisplayRefreshMixin
from ._loader_state import AxeItemKey


class AxeDisplayLoadersMixin(AxeDisplayRefreshMixin):
    """Mixin providing AXE data loading and item-list building."""


__all__ = [
    "AxeDisplayLoadersMixin",
    "AxeItemKey",
    "_axe_item_key",
    "find_axe_item_idx",
    "selected_axe_item_key",
]
