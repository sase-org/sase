"""Thin adapter over the Rust instruction-readout classifier.

The Rust core owns the handoff/declaration scoring precedence shared by
staged and legacy evidence. This module only forwards the host-gathered
request wire and returns the class string, with no Python fallback.
"""

from __future__ import annotations

from typing import Any

from sase.core.rust import require_rust_binding


class _InstructionReadoutError(ValueError):
    """Raised when an instruction-readout request is rejected."""


def classify_instruction_readout(request: dict[str, Any]) -> str:
    """Score one readout request via Rust; return the class string."""
    binding = require_rust_binding("classify_instruction_readout")
    try:
        return str(binding(request))
    except _InstructionReadoutError:
        raise
    except ValueError as exc:
        raise _InstructionReadoutError(str(exc)) from exc
