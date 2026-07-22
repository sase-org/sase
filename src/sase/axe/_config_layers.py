"""Compatibility wrappers for Rust-owned AXE layer composition."""

from __future__ import annotations

from typing import Any

from sase.config.core import ConfigLayer

from ._config_types import AxeConfigDiagnostic
from .config_backend import AxeConfigComposition, compose_axe_config


def compose_axe_layers(layers: list[ConfigLayer]) -> AxeConfigComposition:
    """Return the complete typed Rust composition for *layers*."""
    return compose_axe_config(layers)


def compose_keyed_axe_layers(
    layers: list[ConfigLayer],
) -> tuple[dict[str, Any], dict[str, str], list[AxeConfigDiagnostic]]:
    """Preserve the established tuple API over the Rust composition result."""
    result = compose_axe_layers(layers)
    return (
        result.effective_config,
        result.legacy_provenance(),
        [
            AxeConfigDiagnostic(
                code=item.code,
                message=item.message,
                path=item.path,
                layer=item.layer,
                severity=item.severity,
            )
            for item in result.diagnostics
        ],
    )


__all__ = [
    "compose_axe_layers",
    "compose_keyed_axe_layers",
]
