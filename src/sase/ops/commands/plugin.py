"""Noninteractive plugin install runner used by durable procs."""

from __future__ import annotations

import argparse
from collections.abc import Mapping

from sase.ops.cli import emit_operation_result
from sase.ops.names import PLUGIN_INSTALL


def emit_plugin_install_result(
    *,
    success: bool,
    message: str,
    payload: Mapping[str, object] | None = None,
    args: argparse.Namespace | None = None,
) -> None:
    """Write a typed plugin-install result when a result path is configured."""
    emit_operation_result(
        operation=PLUGIN_INSTALL,
        success=success,
        message=message,
        error=None if success else message,
        payload=payload,
        args=args,
    )


__all__ = ["emit_plugin_install_result"]
