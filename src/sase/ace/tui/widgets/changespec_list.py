"""Legacy aliases for patch list widgets."""

from .patch_list import PatchList, _BANNER_ROW, _get_status_indicator

ChangeSpecList = PatchList  # legacy compatibility alias

__all__ = [
    # legacy compatibility alias
    "ChangeSpecList",
    "_BANNER_ROW",
    "_get_status_indicator",
]  # legacy compatibility alias
