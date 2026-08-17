"""Compatibility facade for create/update/delete bead CLI command handlers.

The handlers themselves live in focused modules; this module keeps the historical
``sase.bead.cli_crud`` import surface intact. Patch the module that defines a
handler (``cli_crud_create``, ``cli_crud_lifecycle``, ...), not this facade.
"""

from __future__ import annotations

from sase.bead.cli_crud_create import (
    handle_bead_create,
    handle_bead_init,
    parse_type_arg,
)
from sase.bead.cli_crud_evidence import handle_bead_note, handle_bead_plus_one
from sase.bead.cli_crud_lifecycle import (
    handle_bead_close,
    handle_bead_open,
    handle_bead_rm,
)
from sase.bead.cli_crud_snooze import handle_bead_snooze
from sase.bead.cli_crud_update import handle_bead_update

_parse_type_arg = parse_type_arg

__all__ = [
    "_parse_type_arg",
    "handle_bead_close",
    "handle_bead_create",
    "handle_bead_init",
    "handle_bead_note",
    "handle_bead_open",
    "handle_bead_plus_one",
    "handle_bead_rm",
    "handle_bead_snooze",
    "handle_bead_update",
    "parse_type_arg",
]
