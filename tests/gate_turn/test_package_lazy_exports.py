"""PEP 562 gate_turn re-exports must not import models at package import."""

from __future__ import annotations

import subprocess
import sys
import textwrap

import sase.gate_turn as gate_turn_package


def _run_probe(source: str) -> None:
    result = subprocess.run(
        [sys.executable, "-c", textwrap.dedent(source)],
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr + result.stdout


def test_gate_turn_package_import_stays_off_models_and_settlement() -> None:
    _run_probe(
        """
        import sys
        import sase.gate_turn
        assert "sase.gate_turn.models" not in sys.modules
        assert "sase.gate_turn.settlement" not in sys.modules
        assert "sase.gate_turn.naming" not in sys.modules
        """
    )


def test_short_gate_turn_id_first_use_loads_naming_only() -> None:
    _run_probe(
        """
        import sys
        from sase.gate_turn import short_gate_turn_id

        assert callable(short_gate_turn_id)
        assert short_gate_turn_id("abcdefghijklmnop")
        assert "sase.gate_turn.naming" in sys.modules
        assert "sase.gate_turn.settlement" not in sys.modules
        """
    )


def test_lazy_dir_includes_public_exports() -> None:
    names = dir(gate_turn_package)
    assert "short_gate_turn_id" in names
    assert "GateTurnRecord" in names
    assert "settle_gate_turn" in names
