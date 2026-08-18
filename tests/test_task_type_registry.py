from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pytest

from sase.config.layers import ConfigLayer
from sase.task_types import hookimpl
from sase.task_types.registry import (
    TASK_TYPE_ENTRY_POINT_GROUP,
    assemble_task_type_registry,
)


@dataclass
class _Dist:
    name: str = "sase-github"
    version: str = "1.2.3"

    @property
    def metadata(self) -> dict[str, str]:
        return {"Name": self.name, "Version": self.version}


@dataclass
class _EntryPoint:
    name: str
    group: str
    plugin: object
    dist: _Dist = field(default_factory=_Dist)
    value: str = "tests:Plugin"

    def load(self) -> object:
        if isinstance(self.plugin, BaseException):
            raise self.plugin
        return self.plugin


def _entry_points(entries: list[_EntryPoint]) -> Any:
    def load(*, group: str) -> list[_EntryPoint]:
        return [entry for entry in entries if entry.group == group]

    return load


def _spec(**overrides: Any) -> dict[str, Any]:
    spec = {
        "schema_version": 1,
        "task_type": "incident",
        "label": "Incident",
        "summary": "A production incident that needs a tracked follow-up.",
        "when_to_use": "File one when an incident is outside the current task's scope.",
    }
    spec.update(overrides)
    return spec


def _empty_layers() -> list[ConfigLayer]:
    return []


def test_registry_includes_builtins_with_no_plugins_or_project_config(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "sase.task_types._project_config.load_config_layers", _empty_layers
    )
    registry = assemble_task_type_registry(entry_points_fn=_entry_points([]))
    assert [record.task_type for record in registry.records] == [
        "bug",
        "ci",
        "feature",
        "flake",
        "memory",
    ]
    assert all(record.provenance.builtin for record in registry.records)
    assert registry.diagnostics == ()


def test_registry_discovers_plugin_task_type_with_resolved_presentation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Plugin:
        @hookimpl
        def task_type_specs(self) -> tuple[dict[str, Any], ...]:
            return (_spec(),)

    monkeypatch.setattr(
        "sase.task_types._project_config.load_config_layers", _empty_layers
    )
    registry = assemble_task_type_registry(
        entry_points_fn=_entry_points(
            [_EntryPoint("github", TASK_TYPE_ENTRY_POINT_GROUP, Plugin)]
        )
    )
    record = registry.by_slug["incident"]
    assert record.provenance.package == "sase-github"
    assert record.resolved_accent_color
    assert record.resolved_glyph
    assert record in registry.agent_creatable


def test_registry_project_config_overrides_plugin_type(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Plugin:
        @hookimpl
        def task_type_specs(self) -> tuple[dict[str, Any], ...]:
            return (_spec(),)

    layer = ConfigLayer(
        name="local",
        path=None,
        exists=True,
        list_strategy="concatenate",
        data={
            "bead": {
                "task_types": [
                    {"use": "sase-github@incident", "agent_creatable": False}
                ]
            }
        },
    )
    monkeypatch.setattr(
        "sase.task_types._project_config.load_config_layers", lambda: [layer]
    )
    registry = assemble_task_type_registry(
        entry_points_fn=_entry_points(
            [_EntryPoint("github", TASK_TYPE_ENTRY_POINT_GROUP, Plugin)]
        )
    )
    record = registry.by_slug["incident"]
    assert record.provenance.source == "project"
    assert record.agent_creatable is False
    assert record not in registry.agent_creatable


def test_registry_rejects_plugin_shadowing_a_builtin(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Plugin:
        @hookimpl
        def task_type_specs(self) -> tuple[dict[str, Any], ...]:
            return (_spec(task_type="bug", label="Not the builtin"),)

    monkeypatch.setattr(
        "sase.task_types._project_config.load_config_layers", _empty_layers
    )
    registry = assemble_task_type_registry(
        entry_points_fn=_entry_points(
            [_EntryPoint("github", TASK_TYPE_ENTRY_POINT_GROUP, Plugin)]
        )
    )
    record = registry.by_slug["bug"]
    assert record.provenance.builtin is True
    assert record.spec["label"] == "Bug"
    assert [d.code for d in registry.diagnostics] == ["builtin_task_type_shadowed"]
