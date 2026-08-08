"""Legacy parser names backed by :mod:`sase.ace.patch.parser`."""

from sase.ace.patch.parser import (
    parse_patch_from_lines,
    parse_patch_project_file,
    parse_patch_project_file_python,
    parse_project_file,
    parse_project_file_python,
)

_parse_changespec_from_lines = parse_patch_from_lines
_parse_patch_from_lines = parse_patch_from_lines

__all__ = [
    "_parse_changespec_from_lines",
    "_parse_patch_from_lines",
    "parse_patch_from_lines",
    "parse_patch_project_file",
    "parse_patch_project_file_python",
    "parse_project_file",
    "parse_project_file_python",
]
