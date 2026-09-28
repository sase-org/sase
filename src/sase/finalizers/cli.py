"""Presentation helpers for the ``sase final`` command group.

Compatibility facade: the implementation lives in
:mod:`sase.finalizers.cli_inventory` and :mod:`sase.finalizers.cli_status`.
This module re-exports the public surface so existing import paths keep working.
"""

from __future__ import annotations

from sase.finalizers.cli_inventory import (
    ConfigFn,
    FINALIZER_CLI_JSON_SCHEMA_VERSION,
    FinalizerInstanceView,
    build_finalizer_inventory,
    handle_final_doctor,
    handle_final_list,
    handle_final_show,
)
from sase.finalizers.cli_status import handle_final_status


__all__ = [
    "ConfigFn",
    "FINALIZER_CLI_JSON_SCHEMA_VERSION",
    "FinalizerInstanceView",
    "build_finalizer_inventory",
    "handle_final_doctor",
    "handle_final_list",
    "handle_final_show",
    "handle_final_status",
]
