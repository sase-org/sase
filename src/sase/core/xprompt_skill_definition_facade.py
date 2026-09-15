"""Resolve xprompt skill source definitions through ``sase_core_rs``."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
import importlib.resources
from pathlib import Path
from typing import Any, cast

from sase.core.rust import require_rust_binding
from sase.main.plugin_discovery import discover_plugin_resources, is_plugin_disabled
from sase.xprompt.loader_skills import get_sase_package_skills_dir

XPROMPT_SKILL_DEFINITION_WIRE_SCHEMA_VERSION = 1


@dataclass(frozen=True, slots=True)
class _XpromptSkillDefinitionCandidate:
    reference: str
    skill_name: str
    project: str | None = None
    definition_path: str | None = None

    @classmethod
    def from_wire(cls, raw: Mapping[str, Any]) -> _XpromptSkillDefinitionCandidate:
        return cls(
            reference=str(raw["reference"]),
            skill_name=str(raw["skill_name"]),
            project=_optional_str(raw.get("project")),
            definition_path=_optional_str(raw.get("definition_path")),
        )


@dataclass(frozen=True, slots=True)
class XpromptSkillDefinitionResolution:
    schema_version: int
    status: str
    authored_reference: str
    canonical_reference: str | None = None
    skill_name: str | None = None
    project: str | None = None
    definition_path: str | None = None
    candidates: tuple[_XpromptSkillDefinitionCandidate, ...] = ()
    diagnostic: str | None = None

    @classmethod
    def from_wire(cls, raw: Mapping[str, Any]) -> XpromptSkillDefinitionResolution:
        version = int(raw["schema_version"])
        if version != XPROMPT_SKILL_DEFINITION_WIRE_SCHEMA_VERSION:
            raise RuntimeError(
                f"sase_core_rs xprompt-skill definition wire is stale: {version}"
            )
        return cls(
            schema_version=version,
            status=str(raw["status"]),
            authored_reference=str(raw["authored_reference"]),
            canonical_reference=_optional_str(raw.get("canonical_reference")),
            skill_name=_optional_str(raw.get("skill_name")),
            project=_optional_str(raw.get("project")),
            definition_path=_optional_str(raw.get("definition_path")),
            candidates=tuple(
                _XpromptSkillDefinitionCandidate.from_wire(
                    cast(Mapping[str, Any], item)
                )
                for item in raw.get("candidates", ())
            ),
            diagnostic=_optional_str(raw.get("diagnostic")),
        )


def resolve_xprompt_skill_definition(
    reference: str,
    *,
    project: str | None = None,
    root_dir: Path | None = None,
) -> XpromptSkillDefinitionResolution:
    """Return the local source definition for a skill reference."""
    _require_xprompt_skill_definition_schema()
    binding = require_rust_binding("resolve_xprompt_skill_definition")
    raw = cast(
        Mapping[str, Any],
        binding(
            {
                "schema_version": XPROMPT_SKILL_DEFINITION_WIRE_SCHEMA_VERSION,
                "reference": reference,
                "project": project,
            },
            _catalog_options(root_dir),
        ),
    )
    return XpromptSkillDefinitionResolution.from_wire(raw)


def _require_xprompt_skill_definition_schema() -> None:
    binding = require_rust_binding("xprompt_skill_definition_wire_schema_version")
    version = int(binding())
    if version != XPROMPT_SKILL_DEFINITION_WIRE_SCHEMA_VERSION:
        raise RuntimeError(
            "sase_core_rs xprompt-skill definition wire is stale: "
            f"expected {XPROMPT_SKILL_DEFINITION_WIRE_SCHEMA_VERSION}, got {version}"
        )


def _catalog_options(root_dir: Path | None) -> dict[str, object]:
    package_root = Path(str(importlib.resources.files("sase")))
    return {
        "root_dir": None if root_dir is None else str(root_dir),
        "package_xprompts_dir": str(package_root / "xprompts"),
        "package_skills_dir": str(get_sase_package_skills_dir(package_root)),
        "default_xprompts_dir": str(package_root / "default_xprompts"),
        "default_config_path": str(package_root / "default_config.yml"),
        "plugin_xprompt_dirs": _plugin_resource_dirs("xprompts"),
        "plugin_skill_dirs": _plugin_resource_dirs("skills"),
        "plugin_config_paths": _plugin_config_paths(),
    }


def _plugin_resource_dirs(resource_dir: str) -> dict[str, str]:
    if is_plugin_disabled("XPROMPTS"):
        return {}
    result: dict[str, str] = {}
    for module in discover_plugin_resources("sase_xprompts"):
        try:
            ref = importlib.resources.files(module).joinpath(resource_dir)
        except (AttributeError, TypeError):
            continue
        path = Path(str(ref))
        if path.is_dir():
            result[getattr(module, "__name__", str(module))] = str(path)
    return result


def _plugin_config_paths() -> dict[str, str]:
    if is_plugin_disabled("CONFIG"):
        return {}
    result: dict[str, str] = {}
    for module in discover_plugin_resources("sase_config"):
        try:
            ref = importlib.resources.files(module).joinpath("default_config.yml")
        except (AttributeError, TypeError):
            continue
        path = Path(str(ref))
        if path.is_file():
            result[getattr(module, "__name__", str(module))] = str(path)
    return result


def _optional_str(value: object) -> str | None:
    if value is None:
        return None
    text = str(value)
    return text if text else None


__all__ = [
    "XPROMPT_SKILL_DEFINITION_WIRE_SCHEMA_VERSION",
    "XpromptSkillDefinitionResolution",
    "resolve_xprompt_skill_definition",
]
