"""Lifecycle argument parser definitions for bead subcommands (facade).

The parsers formerly defined here now live in
``parser_bead_lifecycle_notes.py`` (notes and evidence),
``parser_bead_lifecycle_state.py`` (state changes), and
``parser_bead_lifecycle_work.py`` (launching work). This module re-exports
every public parser so the historic import path keeps working. Only public
names are re-exported; no ``_``-prefixed name is imported across the split
modules.
"""

from __future__ import annotations

from sase.main.parser_bead_lifecycle_notes import (
    register_bead_attach_parser,
    register_bead_attachment_parser,
    register_bead_note_parser,
    register_bead_plus_one_parser,
)
from sase.main.parser_bead_lifecycle_state import (
    register_bead_close_parser,
    register_bead_create_parser,
    register_bead_open_parser,
    register_bead_rm_parser,
    register_bead_snooze_parser,
    register_bead_update_parser,
)
from sase.main.parser_bead_lifecycle_work import (
    register_bead_onboard_parser,
    register_bead_work_parser,
)

__all__ = [
    "register_bead_attach_parser",
    "register_bead_attachment_parser",
    "register_bead_close_parser",
    "register_bead_create_parser",
    "register_bead_note_parser",
    "register_bead_onboard_parser",
    "register_bead_open_parser",
    "register_bead_plus_one_parser",
    "register_bead_rm_parser",
    "register_bead_snooze_parser",
    "register_bead_update_parser",
    "register_bead_work_parser",
]
