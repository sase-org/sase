"""Package lazy-export coverage for archived gate pending-marker names."""

from __future__ import annotations

from importlib import import_module

import sase.gate_turn as gate_turn_package
from sase.gate_turn import GATE_PENDING_MARKER


def test_every_lazy_export_resolves() -> None:
    for name, target in sorted(gate_turn_package._LAZY_EXPORTS.items()):
        module_name, attribute = target
        assert hasattr(import_module(module_name), attribute)
        assert getattr(gate_turn_package, name) is not None


def test_gate_pending_marker_name_is_stable() -> None:
    assert GATE_PENDING_MARKER == ".sase_gate_pending"
