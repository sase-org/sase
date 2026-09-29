"""Shared text for bead lifecycle argument parser definitions.

Public names for the ``parser_bead_lifecycle_*`` modules. Names are public
so the split modules can import them; the module itself is private
(``_``-prefixed) so no ``_``-prefixed name is ever imported across modules.
"""

from __future__ import annotations

from sase.cli_file_values import AT_PATH_PREFIX

__all__ = ["AT_PATH_READS_IT"]

AT_PATH_READS_IT = (
    f"{AT_PATH_PREFIX}<path> reads it from that file, "
    f"{AT_PATH_PREFIX * 2} escapes a literal leading {AT_PATH_PREFIX}"
)
_AT_PATH_READS_THEM = (
    f"{AT_PATH_PREFIX}<path> reads them from that file, "
    f"{AT_PATH_PREFIX * 2} escapes a literal leading {AT_PATH_PREFIX}"
)
