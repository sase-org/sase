from __future__ import annotations

import importlib.util
from importlib.machinery import SourceFileLoader
from pathlib import Path
from types import ModuleType, SimpleNamespace


import pytest

pytestmark = pytest.mark.contract

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
        "plan_reference_parse",
        "plan_reference_render",
        "plan_reference_canonicalize",
        "plan_reference_resolve",
        "plan_reference_resolution_wire_schema_version",
        "sdd_artifact_link_parse",
        "sdd_artifact_link_render",
        "sdd_artifact_link_upsert",
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


def test_validate_sase_core_rs_requires_task_store_bindings() -> None:
    validator = _load_validate_sase_core_rs()
    task_bindings = {
        "read_tasks_snapshot",
        "append_task",
        "update_task",
        "prune_tasks",
    }

    assert task_bindings <= set(validator.REQUIRED_BINDINGS)
    for binding in task_bindings:
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


def test_validate_sase_core_rs_requires_current_artifact_ref_contract() -> None:
    validator = _load_validate_sase_core_rs()
    bindings = {
        "artifact_ref_wire_schema_version": 4,
        "artifact_ref_context_wire_schema_version": 1,
        "artifact_ref_list_resolution_wire_schema_version": 2,
        "artifact_ref_path_filter_wire_schema_version": 1,
    }

    assert bindings.keys() <= set(validator.REQUIRED_BINDINGS)
    assert validator._validate_artifact_ref_schemas(
        SimpleNamespace(
            **{name: lambda value=value: value for name, value in bindings.items()}
        )
    )
    for name, version in bindings.items():
        stale = dict(bindings)
        stale[name] = version + 1
        assert not validator._validate_artifact_ref_schemas(
            SimpleNamespace(
                **{
                    binding: lambda value=value: value
                    for binding, value in stale.items()
                }
            )
        )


def _skill_layout_payload(
    *,
    schema_version: int = 5,
    package_locator: str = "package:xprompts/skills",
) -> dict[str, object]:
    return {
        "schema_version": schema_version,
        "skill_sources": [
            {
                "id": "project_skills",
                "locator": "/workspace/demo/sase/skills",
            },
            {"id": "home_skills", "locator": "/home/alice/sase/skills"},
            {
                "id": "home_project_skills",
                "locator": "/home/alice/sase/skills/demo",
            },
            {"id": "package_skills", "locator": package_locator},
        ],
    }


def test_validate_sase_core_rs_requires_singular_skill_contract() -> None:
    validator = _load_validate_sase_core_rs()
    bindings = {"skill_reference_name", "sase_content_layout"}

    def module(
        *,
        references: dict[tuple[str, str | None], str] | None = None,
        layout: object | None = None,
    ) -> SimpleNamespace:
        references = references or {
            ("foo", None): "skill/foo",
            ("foo", "app"): "app/skill/foo",
        }
        if layout is None:
            layout = _skill_layout_payload()
        return SimpleNamespace(
            skill_reference_name=lambda name, project=None: references[(name, project)],
            sase_content_layout=lambda *_args: layout,
        )

    assert bindings <= set(validator.REQUIRED_BINDINGS)
    assert validator._validate_skill_reference_contract(module())
    assert not validator._validate_skill_reference_contract(
        module(
            references={
                ("foo", None): "skills/foo",
                ("foo", "app"): "app/skills/foo",
            }
        )
    )
    assert not validator._validate_skill_reference_contract(
        module(layout=_skill_layout_payload(schema_version=3))
    )
    assert not validator._validate_skill_reference_contract(
        module(layout=_skill_layout_payload(package_locator="package:skills"))
    )


def test_validate_sase_core_rs_requires_stats_v5_runner_counters() -> None:
    validator = _load_validate_sase_core_rs()

    def module_with_payload(payload: object) -> SimpleNamespace:
        return SimpleNamespace(
            rebuild_agent_artifact_index=lambda *_args: {},
            agent_stats_query_runs=lambda *_args: payload,
        )

    assert not validator._validate_agent_stats_work_schema(
        module_with_payload({"schema_version": 3})
    )
    assert not validator._validate_agent_stats_work_schema(
        module_with_payload(
            {
                "schema_version": 3,
                "work": {"projects": [], "changespecs": []},
            }  # legacy wire key
        )
    )
    assert not validator._validate_agent_stats_work_schema(
        module_with_payload(
            {
                "schema_version": 4,
                "work": {"projects": [], "changespecs": []},
            }  # legacy wire key
        )
    )
    assert not validator._validate_agent_stats_work_schema(
        module_with_payload(
            {
                "schema_version": 5,
                "work": {"projects": [], "changespecs": []},  # legacy wire key
                "xprompts": {"rows": []},
            }
        )
    )
    assert validator._validate_agent_stats_work_schema(
        module_with_payload(
            {
                "schema_version": 5,
                "work": {"projects": [], "changespecs": []},  # legacy wire key
                "xprompts": {"rows": []},
                "runners": {
                    "lanes_counted": 0,
                    "lanes_without_end_skipped": 0,
                    "user_hidden_skipped": 0,
                },
            }
        )
    )


def _write_pyproject(root: Path, dependency: str) -> Path:
    pyproject = root / "pyproject.toml"
    pyproject.write_text(
        f'[project]\ndependencies = ["{dependency}"]\n',
        encoding="utf-8",
    )
    return pyproject


def _write_core_checkout(root: Path, version: str) -> Path:
    core = root / "sase-core"
    core.mkdir()
    (core / "Cargo.toml").write_text(
        f'[workspace.package]\nversion = "{version}"\n',
        encoding="utf-8",
    )
    return core


def test_validate_installed_version_fails_when_below_the_pyproject_floor(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    validator = _load_validate_sase_core_rs()
    monkeypatch.setattr(validator.importlib.metadata, "version", lambda _name: "0.1.0")
    pyproject = _write_pyproject(tmp_path, "sase-core-rs>=0.2.0,<0.3.0")

    assert not validator._validate_installed_version(
        pyproject=pyproject, sase_core_dir=None
    )


def test_validate_installed_version_fails_when_it_disagrees_with_the_checkout(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    validator = _load_validate_sase_core_rs()
    monkeypatch.setattr(validator.importlib.metadata, "version", lambda _name: "0.2.0")
    pyproject = _write_pyproject(tmp_path, "sase-core-rs>=0.2.0,<0.3.0")
    sase_core_dir = _write_core_checkout(tmp_path, "0.2.5")

    assert not validator._validate_installed_version(
        pyproject=pyproject, sase_core_dir=sase_core_dir
    )


def test_validate_installed_version_passes_in_range_and_in_agreement(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    validator = _load_validate_sase_core_rs()
    monkeypatch.setattr(validator.importlib.metadata, "version", lambda _name: "0.2.0")
    pyproject = _write_pyproject(tmp_path, "sase-core-rs>=0.2.0,<0.3.0")
    sase_core_dir = _write_core_checkout(tmp_path, "0.2.0")

    assert validator._validate_installed_version(
        pyproject=pyproject, sase_core_dir=sase_core_dir
    )


def test_validate_installed_version_only_enforces_the_floor_not_the_ceiling(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Dev builds intentionally run ahead of the published window (see
    `_core-overrides-arg` in the Justfile), so a distribution version above
    the upper bound must not fail this check.
    """
    validator = _load_validate_sase_core_rs()
    monkeypatch.setattr(validator.importlib.metadata, "version", lambda _name: "0.99.0")
    pyproject = _write_pyproject(tmp_path, "sase-core-rs>=0.2.0,<0.3.0")

    assert validator._validate_installed_version(
        pyproject=pyproject, sase_core_dir=None
    )
