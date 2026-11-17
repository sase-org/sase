"""PEP 562 notification_gates re-exports must not import executor at import."""

from __future__ import annotations

import subprocess
import sys
import textwrap
from importlib import import_module

import sase.notification_gates as gates_package


def _run_probe(source: str) -> None:
    result = subprocess.run(
        [sys.executable, "-c", textwrap.dedent(source)],
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr + result.stdout


def test_every_lazy_export_resolves() -> None:
    for name, target in sorted(gates_package._LAZY_EXPORTS.items()):
        module_name, attribute = target
        assert hasattr(import_module(module_name), attribute)
        assert getattr(gates_package, name) is not None


def test_package_import_stays_off_executor_poller_and_service() -> None:
    _run_probe(
        """
        import sys
        import sase.notification_gates
        assert "sase.notification_gates.executor" not in sys.modules
        assert "sase.notification_gates.poller" not in sys.modules
        assert "sase.notification_gates.service" not in sys.modules
        assert "sase.notification_gates.models" not in sys.modules
        assert "sase.notification_gates.registry" not in sys.modules
        """
    )


def test_adapter_for_action_first_use_loads_registry() -> None:
    _run_probe(
        """
        import sys
        from sase.notification_gates import adapter_for_action, PRIVILEGED_GATE_ACTIONS

        assert callable(adapter_for_action)
        assert "HITL" in PRIVILEGED_GATE_ACTIONS
        assert adapter_for_action("missing-action") is None
        assert "sase.notification_gates.registry" in sys.modules
        assert "sase.notification_gates.executor" not in sys.modules
        assert "sase.notification_gates.service" not in sys.modules
        """
    )


def test_lazy_dir_includes_public_exports() -> None:
    names = dir(gates_package)
    assert "adapter_for_action" in names
    assert "PRIVILEGED_GATE_ACTIONS" in names
    assert "create_gate" in names
