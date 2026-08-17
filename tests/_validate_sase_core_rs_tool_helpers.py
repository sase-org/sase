from __future__ import annotations

import importlib.util
from importlib.machinery import SourceFileLoader
from pathlib import Path
from types import ModuleType, SimpleNamespace


ROOT = Path(__file__).resolve().parents[1]


def load_validate_sase_core_rs() -> ModuleType:
    script = ROOT / "tools" / "validate_sase_core_rs"
    loader = SourceFileLoader("validate_sase_core_rs_tool", str(script))
    spec = importlib.util.spec_from_file_location(
        "validate_sase_core_rs_tool",
        script,
        loader=loader,
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def module_with_required_bindings(
    validator: ModuleType,
    *,
    missing: set[str] | None = None,
) -> SimpleNamespace:
    missing = missing or set()
    return SimpleNamespace(
        **{
            name: lambda: None
            for name in validator.REQUIRED_BINDINGS
            if name not in missing
        }
    )
