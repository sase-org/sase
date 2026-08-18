from __future__ import annotations

from typing import Any

from sase.config.layers import ConfigLayer
from sase.task_types._models import (
    TaskTypeDiagnostic,
    TaskTypeProvenance,
    TaskTypeRecord,
)
from sase.task_types._project_config import apply_project_task_type_config


def _layer(
    name: str, task_types: object, *, strategy: str = "concatenate"
) -> ConfigLayer:
    return ConfigLayer(
        name=name,
        path=None,
        exists=True,
        list_strategy=strategy,
        data={"bead": {"task_types": task_types}},
    )


def _base_spec(**overrides: Any) -> dict[str, Any]:
    spec = {
        "schema_version": 1,
        "task_type": "flake",
        "label": "Flaky test",
        "summary": "A test that fails and then passes on an unchanged tree.",
        "when_to_use": "File one when a test failed and a rerun on the same tree passed.",
        "triage": {"min_plus_ones": 1},
    }
    spec.update(overrides)
    return spec


def _builtin_record(**overrides: Any) -> TaskTypeRecord:
    spec = _base_spec(**overrides)
    return TaskTypeRecord(
        task_type=spec["task_type"],
        spec=spec,
        digest="0" * 64,
        provenance=TaskTypeProvenance(
            source="builtin", name="sase", package="sase", version="1.0.0", builtin=True
        ),
    )


def test_use_override_deep_merges_sibling_keys(monkeypatch: Any) -> None:
    monkeypatch.setattr(
        "sase.task_types._project_config.load_config_layers",
        lambda: [
            _layer(
                "local",
                [{"use": "builtin@flake", "triage": {"min_plus_ones": 2}}],
            )
        ],
    )
    diagnostics: list[TaskTypeDiagnostic] = []
    records = apply_project_task_type_config((_builtin_record(),), diagnostics)
    assert diagnostics == []
    assert len(records) == 1
    assert records[0].spec["triage"]["min_plus_ones"] == 2
    assert records[0].spec["label"] == "Flaky test"
    assert records[0].provenance.source == "project"


def test_use_override_rejects_unknown_slug(monkeypatch: Any) -> None:
    monkeypatch.setattr(
        "sase.task_types._project_config.load_config_layers",
        lambda: [_layer("local", [{"use": "builtin@nope"}])],
    )
    diagnostics: list[TaskTypeDiagnostic] = []
    records = apply_project_task_type_config((), diagnostics)
    assert records == ()
    assert [d.code for d in diagnostics] == ["unknown_task_type_use"]


def test_use_override_rejects_bare_value_missing_prefix(monkeypatch: Any) -> None:
    monkeypatch.setattr(
        "sase.task_types._project_config.load_config_layers",
        lambda: [_layer("local", [{"use": "flake"}])],
    )
    diagnostics: list[TaskTypeDiagnostic] = []
    records = apply_project_task_type_config((_builtin_record(),), diagnostics)
    assert records == (_builtin_record(),)
    assert [d.code for d in diagnostics] == ["missing_use_prefix"]


def test_use_override_rejects_mismatched_plugin_prefix(monkeypatch: Any) -> None:
    monkeypatch.setattr(
        "sase.task_types._project_config.load_config_layers",
        lambda: [_layer("local", [{"use": "sase-github@flake"}])],
    )
    diagnostics: list[TaskTypeDiagnostic] = []
    records = apply_project_task_type_config((_builtin_record(),), diagnostics)
    assert records == (_builtin_record(),)
    assert [d.code for d in diagnostics] == ["mismatched_use_prefix"]


def test_new_project_type_defines_new_slug(monkeypatch: Any) -> None:
    monkeypatch.setattr(
        "sase.task_types._project_config.load_config_layers",
        lambda: [_layer("local", [_base_spec(task_type="incident")])],
    )
    diagnostics: list[TaskTypeDiagnostic] = []
    records = apply_project_task_type_config((), diagnostics)
    assert diagnostics == []
    assert len(records) == 1
    assert records[0].task_type == "incident"
    assert records[0].provenance.source == "project"
    assert records[0].provenance.package == "sase"


def test_new_project_type_cannot_shadow_builtin(monkeypatch: Any) -> None:
    monkeypatch.setattr(
        "sase.task_types._project_config.load_config_layers",
        lambda: [_layer("local", [_base_spec()])],
    )
    diagnostics: list[TaskTypeDiagnostic] = []
    records = apply_project_task_type_config((_builtin_record(),), diagnostics)
    assert records == (_builtin_record(),)
    assert [d.code for d in diagnostics] == ["builtin_task_type_shadowed"]


def test_replace_list_strategy_resets_earlier_layers(monkeypatch: Any) -> None:
    monkeypatch.setattr(
        "sase.task_types._project_config.load_config_layers",
        lambda: [
            _layer("global", [_base_spec(task_type="incident")]),
            _layer(
                "local",
                [_base_spec(task_type="postmortem")],
                strategy="replace",
            ),
        ],
    )
    diagnostics: list[TaskTypeDiagnostic] = []
    records = apply_project_task_type_config((), diagnostics)
    assert diagnostics == []
    assert [record.task_type for record in records] == ["postmortem"]
