"""Legacy archive names backed by :mod:`sase.ace.patch.archive`."""

from sase.ace.patch.archive import (
    extract_patch_block,
    get_archive_file_path,
    get_main_file_path,
    is_archive_file,
    move_changespec_to_file,
    move_patch_to_file,
)

_extract_changespec_block = extract_patch_block
_extract_patch_block = extract_patch_block

__all__ = [
    "extract_patch_block",
    "get_archive_file_path",
    "get_main_file_path",
    "is_archive_file",
    "_extract_changespec_block",
    "_extract_patch_block",
    "move_changespec_to_file",
    "move_patch_to_file",
]
