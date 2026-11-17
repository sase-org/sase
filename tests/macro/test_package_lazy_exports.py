"""PEP 562 package re-exports must not run jinja/loader/processor at import."""

from __future__ import annotations

import subprocess
import sys
import textwrap
from importlib import import_module

import sase.macro as macro_package


def _run_probe(source: str) -> None:
    result = subprocess.run(
        [sys.executable, "-c", textwrap.dedent(source)],
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr + result.stdout


def test_every_lazy_export_resolves() -> None:
    for name, target in sorted(macro_package._LAZY_EXPORTS.items()):
        module_name, attribute = target
        assert hasattr(import_module(module_name), attribute)
        assert getattr(macro_package, name) is not None


def test_macro_package_import_stays_off_jinja_loader_and_processor() -> None:
    _run_probe(
        """
        import sys
        import sase.macro
        assert "sase.macro.jinja_assist" not in sys.modules
        assert "sase.macro.jinja_inspect" not in sys.modules
        assert "sase.macro.loader" not in sys.modules
        assert "sase.macro.processor" not in sys.modules
        assert "sase.macro.workflow_runner" not in sys.modules
        """
    )


def test_macro_models_import_does_not_execute_package_closures() -> None:
    _run_probe(
        """
        import sys
        from sase.macro.models import InputArg

        assert InputArg is not None
        assert "sase.macro.jinja_assist" not in sys.modules
        assert "sase.macro.processor" not in sys.modules
        assert "sase.macro.workflow_runner" not in sys.modules
        assert "sase.macro.loader" not in sys.modules
        """
    )


def test_input_arg_first_use_resolves_through_package() -> None:
    _run_probe(
        """
        import sase.macro
        from sase.macro import InputArg

        assert InputArg.__name__ == "InputArg"
        assert "InputArg" in dir(sase.macro)
        """
    )


def test_hitl_result_resolves_without_workflow_executor() -> None:
    _run_probe(
        """
        import sys
        from sase.macro import HITLResult

        assert HITLResult.__name__ == "HITLResult"
        assert "sase.macro.workflow_executor" not in sys.modules
        """
    )
