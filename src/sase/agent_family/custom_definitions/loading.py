"""File and mapping loaders for custom agent-family definitions."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

import yaml  # type: ignore[import-untyped]

from sase.agent_family.custom_definitions.models import AgentFamilyDefinition
from sase.agent_family.custom_definitions.validation import (
    AgentFamilyDefinitionError,
    parse_agent_family_definition,
)
from sase.xprompt.load_issues import record_load_issue


def load_agent_family_definition_from_file(
    file_path: Path,
    *,
    project: str | None = None,
    validate_prompt_refs: bool = True,
) -> AgentFamilyDefinition | None:
    """Load an ``agent_family`` definition from *file_path* if present."""

    try:
        content = file_path.read_text(encoding="utf-8")
        data = yaml.safe_load(content)
    except OSError as exc:
        record_load_issue(file_path, exc, kind="agent_family")
        return None
    except yaml.YAMLError as exc:
        record_load_issue(file_path, exc, kind="agent_family")
        return None
    return load_agent_family_definition_from_mapping(
        data,
        str(file_path),
        project=project,
        validate_prompt_refs=validate_prompt_refs,
    )


def load_agent_family_definition_from_mapping(
    data: object,
    source_path: str,
    *,
    project: str | None = None,
    validate_prompt_refs: bool = True,
) -> AgentFamilyDefinition | None:
    """Load an ``agent_family`` definition from parsed YAML data."""

    if not isinstance(data, Mapping):
        return None
    if data.get("kind") != "agent_family":
        return None

    try:
        return parse_agent_family_definition(
            data,
            source_path,
            project=project,
            validate_prompt_refs=validate_prompt_refs,
        )
    except AgentFamilyDefinitionError as exc:
        record_load_issue(source_path, exc, kind="agent_family")
        return None


def is_agent_family_definition_mapping(data: object) -> bool:
    """Return whether *data* is a top-level ``kind: agent_family`` mapping."""

    return isinstance(data, Mapping) and data.get("kind") == "agent_family"
