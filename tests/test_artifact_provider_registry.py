from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pytest

from sase.artifact_providers import (
    assemble_artifact_provider_registry,
    builtin_plan_ref_provider_spec,
    hookimpl,
)
from sase.artifact_providers.registry import (
    ARTIFACT_REF_ENTRY_POINT_GROUP,
    FILE_HOOK_ENTRY_POINT_GROUP,
)


@dataclass
class _Dist:
    name: str = "sase-research"
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


def _research_spec(**updates: Any) -> dict[str, Any]:
    spec = builtin_plan_ref_provider_spec()
    spec["provider"] = "research"
    spec["ref"]["kind"] = "research"
    spec["ref"]["properties"] = {}
    spec["ref"]["detail"] = {}
    spec["ref"]["identity"] = {}
    spec["ref"]["inventory"] = {"globs": ["reports/**/*.md"]}
    spec.update(updates)
    return spec


def _entry_points(entries: list[_EntryPoint]) -> Any:
    def load(*, group: str) -> list[_EntryPoint]:
        return [entry for entry in entries if entry.group == group]

    return load


def test_registry_registers_builtin_plan_and_entry_kind_descriptors() -> None:
    registry = assemble_artifact_provider_registry(entry_points_fn=_entry_points([]))

    assert registry.ref_providers_by_id["plan"].kind == "plan"
    assert len(registry.ref_providers_by_id["plan"].digest) == 64
    kinds = {entry["kind"] for entry in registry.entry_kinds}
    assert {"stitch", "patch", "bead", "agent", "file"}.issubset(kinds)
    assert registry.diagnostics == ()


def test_registry_discovers_ref_providers_with_provenance() -> None:
    class Plugin:
        @hookimpl
        def artifact_ref_provider_specs(self) -> tuple[dict[str, Any], ...]:
            return (_research_spec(),)

    registry = assemble_artifact_provider_registry(
        entry_points_fn=_entry_points(
            [_EntryPoint("research", ARTIFACT_REF_ENTRY_POINT_GROUP, Plugin)]
        )
    )

    record = registry.ref_providers_by_id["research"]
    assert record.kind == "research"
    assert record.provenance.package == "sase-research"
    assert record.provenance.version == "1.2.3"


def test_registry_skips_duplicate_and_invalid_ref_providers() -> None:
    class First:
        @hookimpl
        def artifact_ref_provider_specs(self) -> tuple[dict[str, Any], ...]:
            return (_research_spec(),)

    class Duplicate:
        @hookimpl
        def artifact_ref_provider_specs(self) -> tuple[dict[str, Any], ...]:
            return (_research_spec(),)

    class Reserved:
        @hookimpl
        def artifact_ref_provider_specs(self) -> tuple[dict[str, Any], ...]:
            spec = _research_spec()
            spec["provider"] = "bad_file"
            spec["ref"]["kind"] = "file"
            return (spec,)

    registry = assemble_artifact_provider_registry(
        entry_points_fn=_entry_points(
            [
                _EntryPoint("a-first", ARTIFACT_REF_ENTRY_POINT_GROUP, First),
                _EntryPoint("z-duplicate", ARTIFACT_REF_ENTRY_POINT_GROUP, Duplicate),
                _EntryPoint("reserved", ARTIFACT_REF_ENTRY_POINT_GROUP, Reserved),
            ]
        )
    )

    assert registry.ref_providers_by_id["research"].provenance.name == "a-first"
    assert "bad_file" not in registry.ref_providers_by_id
    codes = {diagnostic.code for diagnostic in registry.diagnostics}
    assert "duplicate_ref_provider" in codes
    assert "invalid_ref_provider" in codes


def test_registry_discovers_file_hook_provider_templates() -> None:
    class Plugin:
        @hookimpl
        def artifact_file_hook_provider_specs(self) -> tuple[dict[str, Any], ...]:
            return (
                {
                    "schema_version": 1,
                    "provider": "research-highlights",
                    "required": ["command"],
                    "file_hook": {
                        "description": "Render research highlights.",
                        "filters": {
                            "sidecars": ["research"],
                            "path_globs": ["reports/**/*.md"],
                        },
                        "timeout": "30s",
                    },
                },
            )

    registry = assemble_artifact_provider_registry(
        entry_points_fn=_entry_points(
            [_EntryPoint("hooks", FILE_HOOK_ENTRY_POINT_GROUP, Plugin)]
        )
    )

    record = registry.file_hook_providers_by_id["research-highlights"]
    assert record.required_fields == ("command",)
    assert record.template["filters"]["sidecars"] == ["research"]


def test_registry_honors_independent_disable_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class RefPlugin:
        @hookimpl
        def artifact_ref_provider_specs(self) -> tuple[dict[str, Any], ...]:
            return (_research_spec(),)

    class HookPlugin:
        @hookimpl
        def artifact_file_hook_provider_specs(self) -> tuple[dict[str, Any], ...]:
            return (
                {
                    "schema_version": 1,
                    "provider": "research-highlights",
                    "file_hook": {"command": "run"},
                },
            )

    monkeypatch.setenv("SASE_DISABLE_PLUGIN_FILE_HOOKS", "1")

    registry = assemble_artifact_provider_registry(
        entry_points_fn=_entry_points(
            [
                _EntryPoint("research", ARTIFACT_REF_ENTRY_POINT_GROUP, RefPlugin),
                _EntryPoint("hooks", FILE_HOOK_ENTRY_POINT_GROUP, HookPlugin),
            ]
        )
    )

    assert "research" in registry.ref_providers_by_id
    assert registry.file_hook_providers_by_id == {}
    assert registry.disabled_env == ("SASE_DISABLE_PLUGIN_FILE_HOOKS",)
