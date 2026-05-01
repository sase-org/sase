"""Compatibility exports for general bead CLI command handlers."""

from __future__ import annotations

from sase.bead.cli_admin import (
    handle_bead_dep,
    handle_bead_doctor,
    handle_bead_onboard,
    handle_bead_sync,
)
from sase.bead.cli_crud import (
    handle_bead_close,
    handle_bead_create,
    handle_bead_init,
    handle_bead_open,
    handle_bead_rm,
    handle_bead_update,
    parse_type_arg,
)
from sase.bead.cli_query import (
    handle_bead_blocked,
    handle_bead_list,
    handle_bead_ready,
    handle_bead_show,
    handle_bead_stats,
)

_parse_type_arg = parse_type_arg

__all__ = [
    "_parse_type_arg",
    "handle_bead_blocked",
    "handle_bead_close",
    "handle_bead_create",
    "handle_bead_dep",
    "handle_bead_doctor",
    "handle_bead_init",
    "handle_bead_list",
    "handle_bead_onboard",
    "handle_bead_open",
    "handle_bead_ready",
    "handle_bead_rm",
    "handle_bead_show",
    "handle_bead_stats",
    "handle_bead_sync",
    "handle_bead_update",
]
