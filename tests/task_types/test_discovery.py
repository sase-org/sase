from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pytest

from sase.task_types._discovery import (
    TASK_TYPE_ENTRY_POINT_GROUP,
    discover_task_type_specs,
)
from sase.task_types._hookspec import hookimpl


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
        "task_type": "bug",
        "label": "Bug",
        "summary": "A defect an agent found while doing unrelated work.",
        "when_to_use": "File one when you find a bug outside the current task's scope.",
    }
    spec.update(overrides)
    return spec


def test_discovery_collects_builtins_with_no_specs_yet() -> None:
    discovery = discover_task_type_specs(entry_points_fn=_entry_points([]))
    assert discovery.candidates == ()
    assert discovery.diagnostics == ()


def test_discovery_collects_entry_point_specs_with_provenance() -> None:
    class Plugin:
        @hookimpl
        def task_type_specs(self) -> tuple[dict[str, Any], ...]:
            return (_spec(),)

    discovery = discover_task_type_specs(
        entry_points_fn=_entry_points(
            [_EntryPoint("github", TASK_TYPE_ENTRY_POINT_GROUP, Plugin)]
        )
    )
    assert len(discovery.candidates) == 1
    spec, provenance = discovery.candidates[0]
    assert spec["task_type"] == "bug"
    assert provenance.source == "plugin"
    assert provenance.package == "sase-github"
    assert provenance.version == "1.2.3"


def test_discovery_isolates_entry_point_load_failures() -> None:
    discovery = discover_task_type_specs(
        entry_points_fn=_entry_points(
            [_EntryPoint("broken", TASK_TYPE_ENTRY_POINT_GROUP, RuntimeError("boom"))]
        )
    )
    assert discovery.candidates == ()
    assert [d.code for d in discovery.diagnostics] == ["entry_point_load_failed"]
    assert discovery.diagnostics[0].severity == "error"


def test_discovery_honors_disable_env(monkeypatch: pytest.MonkeyPatch) -> None:
    class Plugin:
        @hookimpl
        def task_type_specs(self) -> tuple[dict[str, Any], ...]:
            return (_spec(),)

    monkeypatch.setenv("SASE_DISABLE_PLUGIN_TASK_TYPES", "1")
    discovery = discover_task_type_specs(
        entry_points_fn=_entry_points(
            [_EntryPoint("github", TASK_TYPE_ENTRY_POINT_GROUP, Plugin)]
        )
    )
    assert discovery.candidates == ()
    assert discovery.disabled_env == ("SASE_DISABLE_PLUGIN_TASK_TYPES",)


def test_discovery_honors_global_disable_env(monkeypatch: pytest.MonkeyPatch) -> None:
    class Plugin:
        @hookimpl
        def task_type_specs(self) -> tuple[dict[str, Any], ...]:
            return (_spec(),)

    monkeypatch.setenv("SASE_DISABLE_PLUGINS", "1")
    discovery = discover_task_type_specs(
        entry_points_fn=_entry_points(
            [_EntryPoint("github", TASK_TYPE_ENTRY_POINT_GROUP, Plugin)]
        )
    )
    assert discovery.candidates == ()
    assert discovery.disabled_env == ("SASE_DISABLE_PLUGINS",)
