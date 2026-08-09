"""Legacy aliases for patch list banner helpers."""

from ._patch_list_banner import banner_natural_width, format_patch_banner_option

format_changespec_banner_option = format_patch_banner_option

__all__ = [
    "banner_natural_width",
    "format_changespec_banner_option",
]
