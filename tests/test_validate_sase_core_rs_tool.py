from __future__ import annotations

import importlib.util
from importlib.machinery import SourceFileLoader
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
CUSTOM_ROLE = {
    "id": "tester",
    "label": "TESTING",
    "done_label": "TESTED",
}


def _load_validate_sase_core_rs() -> ModuleType:
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


def _scanner_with_custom_role(value: Any) -> SimpleNamespace:
    def scan_agent_artifacts(
        _projects_root: str,
        _options: dict[str, Any],
    ) -> dict[str, Any]:
        return {
            "records": [
                {
                    "timestamp": "20260427110600",
                    "agent_meta": {"agent_family_custom_role": value},
                }
            ]
        }

    return SimpleNamespace(scan_agent_artifacts=scan_agent_artifacts)


def _module_with_required_bindings(
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


def test_validate_sase_core_rs_requires_plan_validation_bindings() -> None:
    validator = _load_validate_sase_core_rs()
    plan_bindings = {"plan_validate", "plan_frontmatter_schema"}

    assert plan_bindings <= set(validator.REQUIRED_BINDINGS)
    assert validator._validate_bindings(_module_with_required_bindings(validator))
    for binding in plan_bindings:
        assert not validator._validate_bindings(
            _module_with_required_bindings(validator, missing={binding})
        )


def test_validate_sase_core_rs_accepts_custom_role_agent_meta_probe() -> None:
    validator = _load_validate_sase_core_rs()

    assert validator._validate_agent_meta_custom_role(
        _scanner_with_custom_role(CUSTOM_ROLE)
    )


def test_validate_sase_core_rs_rejects_missing_custom_role_agent_meta() -> None:
    validator = _load_validate_sase_core_rs()

    assert not validator._validate_agent_meta_custom_role(
        _scanner_with_custom_role(None)
    )
