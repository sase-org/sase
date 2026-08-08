"""Compatibility shim for :mod:`sase.ace.patch.parser`."""

from sase.ace.patch.parser import *  # noqa: F403
from sase.ace.patch.parser import (  # noqa: F401
    parse_patch_from_lines as _parse_changespec_from_lines,
    parse_patch_project_file_python,
    parse_project_file_python,
)
