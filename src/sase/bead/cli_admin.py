"""Compatibility facade for administrative bead CLI command handlers.

The handlers themselves live in focused modules; this module keeps the historical
``sase.bead.cli_admin`` import surface intact. Patch the module that defines a
handler (``cli_admin_doctor``, ``cli_admin_onboard``, ``cli_admin_sync``), not
this facade.
"""

from __future__ import annotations

from sase.bead.cli_admin_doctor import handle_bead_doctor
from sase.bead.cli_admin_onboard import handle_bead_onboard
from sase.bead.cli_admin_sync import (
    handle_bead_export,
    handle_bead_resolve_conflicts,
    handle_bead_sync,
)

__all__ = [
    "handle_bead_doctor",
    "handle_bead_export",
    "handle_bead_onboard",
    "handle_bead_resolve_conflicts",
    "handle_bead_sync",
]
