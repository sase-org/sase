from __future__ import annotations

import importlib.util
from importlib.machinery import SourceFileLoader
from pathlib import Path
from types import ModuleType, SimpleNamespace


ROOT = Path(__file__).resolve().parents[1]


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
    plan_bindings = {
        "plan_validate",
        "plan_frontmatter_schema",
        "sdd_frontmatter_link_parse",
        "sdd_frontmatter_link_render",
    }

    assert plan_bindings <= set(validator.REQUIRED_BINDINGS)
    assert validator._validate_bindings(_module_with_required_bindings(validator))
    for binding in plan_bindings:
        assert not validator._validate_bindings(
            _module_with_required_bindings(validator, missing={binding})
        )


def test_validate_sase_core_rs_requires_inline_code_binding() -> None:
    validator = _load_validate_sase_core_rs()

    assert "inline_code_ranges" in validator.REQUIRED_BINDINGS
    assert not validator._validate_bindings(
        _module_with_required_bindings(
            validator,
            missing={"inline_code_ranges"},
        )
    )


def test_validate_sase_core_rs_requires_telemetry_bindings() -> None:
    validator = _load_validate_sase_core_rs()
    telemetry_bindings = {
        "telemetry_record_batch",
        "telemetry_query_instant",
        "telemetry_query_range",
        "telemetry_prune",
        "telemetry_store_stats",
    }

    assert telemetry_bindings <= set(validator.REQUIRED_BINDINGS)
    for binding in telemetry_bindings:
        assert not validator._validate_bindings(
            _module_with_required_bindings(validator, missing={binding})
        )


def test_validate_sase_core_rs_requires_agent_stats_work_bindings() -> None:
    validator = _load_validate_sase_core_rs()
    stats_bindings = {
        "rebuild_agent_artifact_index",
        "agent_stats_query_runs",
        "agent_stats_query_activity",
    }

    assert stats_bindings <= set(validator.REQUIRED_BINDINGS)
    for binding in stats_bindings:
        assert not validator._validate_bindings(
            _module_with_required_bindings(validator, missing={binding})
        )


def test_validate_sase_core_rs_requires_cleanup_wire_version_binding() -> None:
    validator = _load_validate_sase_core_rs()

    assert "agent_cleanup_wire_schema_version" in validator.REQUIRED_BINDINGS
    assert not validator._validate_bindings(
        _module_with_required_bindings(
            validator,
            missing={"agent_cleanup_wire_schema_version"},
        )
    )


def test_validate_sase_core_rs_requires_agent_stats_schema_v2() -> None:
    validator = _load_validate_sase_core_rs()

    def module_with_payload(payload: object) -> SimpleNamespace:
        return SimpleNamespace(
            rebuild_agent_artifact_index=lambda *_args: {},
            agent_stats_query_runs=lambda *_args: payload,
        )

    assert not validator._validate_agent_stats_work_schema(
        module_with_payload({"schema_version": 1})
    )
    assert not validator._validate_agent_stats_work_schema(
        module_with_payload({"schema_version": 2})
    )
    assert validator._validate_agent_stats_work_schema(
        module_with_payload(
            {
                "schema_version": 2,
                "work": {"projects": [], "changespecs": []},
            }
        )
    )
