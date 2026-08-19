"""Machine-global builtin task-type specs used by the home instruction note."""

from __future__ import annotations

from typing import Any

from sase.config.layers import ConfigLayer
from sase.task_types.registry import machine_global_builtin_task_type_specs


_BUILTIN_SLUGS = ("bug", "ci", "feature", "flake", "memory")


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


def _new_slug_spec(task_type: str = "incident") -> dict[str, Any]:
    return {
        "schema_version": 1,
        "task_type": task_type,
        "label": "Incident",
        "summary": "A production incident that needs a tracked follow-up.",
        "when_to_use": "File one when an incident is outside the current task's scope.",
        "triage": {"min_plus_ones": 0},
    }


def test_machine_global_specs_are_the_five_builtins_with_no_config(
    monkeypatch: Any,
) -> None:
    monkeypatch.setattr(
        "sase.task_types._project_config.load_config_layers", lambda: []
    )
    specs = machine_global_builtin_task_type_specs()
    assert [spec["task_type"] for spec in specs] == list(_BUILTIN_SLUGS)
    assert all(spec.get("agent_creatable", True) for spec in specs)


def test_machine_global_specs_apply_a_user_layer_disable(monkeypatch: Any) -> None:
    monkeypatch.setattr(
        "sase.task_types._project_config.load_config_layers",
        lambda: [
            _layer("user", [{"use": "builtin@feature", "agent_creatable": False}]),
        ],
    )
    specs = machine_global_builtin_task_type_specs()
    by_slug = {spec["task_type"]: spec for spec in specs}
    assert tuple(by_slug) == _BUILTIN_SLUGS
    assert by_slug["feature"]["agent_creatable"] is False


def test_machine_global_specs_ignore_a_local_layer_disable(monkeypatch: Any) -> None:
    monkeypatch.setattr(
        "sase.task_types._project_config.load_config_layers",
        lambda: [
            _layer("local", [{"use": "builtin@bug", "agent_creatable": False}]),
        ],
    )
    specs = machine_global_builtin_task_type_specs()
    by_slug = {spec["task_type"]: spec for spec in specs}
    assert by_slug["bug"].get("agent_creatable", True) is True


def test_machine_global_specs_exclude_a_new_machine_global_slug(
    monkeypatch: Any,
) -> None:
    monkeypatch.setattr(
        "sase.task_types._project_config.load_config_layers",
        lambda: [_layer("user", [_new_slug_spec()])],
    )
    specs = machine_global_builtin_task_type_specs()
    assert [spec["task_type"] for spec in specs] == list(_BUILTIN_SLUGS)
    assert "incident" not in {spec["task_type"] for spec in specs}
