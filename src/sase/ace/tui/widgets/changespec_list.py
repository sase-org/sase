"""Legacy aliases for patch list widgets."""

from .patch_list import PatchList, _BANNER_ROW, _get_status_indicator

ChangeSpecList = PatchList

__all__ = ["ChangeSpecList", "_BANNER_ROW", "_get_status_indicator"]
