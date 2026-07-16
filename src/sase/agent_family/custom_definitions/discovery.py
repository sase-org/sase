"""Discovery for active custom agent-family definitions."""

from __future__ import annotations

import importlib.resources
import tempfile
from dataclasses import asdict
from pathlib import Path

from sase.agent_family.custom_definitions.loading import (
    load_agent_family_definition_from_file,
)
from sase.agent_family.custom_definitions.models import (
    AgentFamilyDefinition,
    AgentFamilyRoleDefinition,
)
from sase.content_layout import resolve_xprompt_file_sources
from sase.core.paths import get_sase_tmpdir
from sase.main.plugin_discovery import discover_plugin_resources, is_plugin_disabled
from sase.xprompt.loader import (
    detect_project,
    get_known_project_workspaces,
    get_sase_package_xprompts_dir,
    get_xprompt_search_paths,
)


def get_all_agent_family_definitions(
    project: str | None = None,
    *,
    validate_prompt_refs: bool = True,
) -> dict[str, AgentFamilyDefinition]:
    """Load all active custom family definitions for *project*.

    Priority mirrors xprompt/workflow discovery. Bundled example definitions
    live under ``xprompts/examples`` and are intentionally not active.
    """

    effective_project = project if project is not None else detect_project()
    definitions: dict[str, AgentFamilyDefinition] = {}

    definitions.update(
        _load_definitions_from_dir(
            get_sase_package_xprompts_dir(),
            project=effective_project,
            validate_prompt_refs=validate_prompt_refs,
        )
    )
    definitions.update(
        _load_definitions_from_plugins(
            project=effective_project,
            validate_prompt_refs=validate_prompt_refs,
        )
    )
    if effective_project:
        definitions.update(
            _load_definitions_from_project_dir(
                effective_project,
                validate_prompt_refs=validate_prompt_refs,
            )
        )
        definitions.update(
            _load_definitions_from_project_workspace(
                effective_project,
                validate_prompt_refs=validate_prompt_refs,
            )
        )
    definitions.update(
        _load_definitions_from_files(
            project=effective_project,
            validate_prompt_refs=validate_prompt_refs,
        )
    )
    return definitions


def active_roles_after(
    after_role: str,
    *,
    project: str | None = None,
    validate_prompt_refs: bool = True,
) -> tuple[AgentFamilyRoleDefinition, ...]:
    """Return loaded custom roles placed after *after_role*."""

    roles: list[AgentFamilyRoleDefinition] = []
    for definition in get_all_agent_family_definitions(
        project=project,
        validate_prompt_refs=validate_prompt_refs,
    ).values():
        roles.extend(
            role for role in definition.roles if role.placement_after == after_role
        )
    return tuple(sorted(roles, key=lambda role: (role.source_path, role.id)))


def _load_definitions_from_dir(
    directory: Path,
    *,
    project: str | None,
    validate_prompt_refs: bool,
) -> dict[str, AgentFamilyDefinition]:
    definitions: dict[str, AgentFamilyDefinition] = {}
    if not directory.is_dir():
        return definitions
    for pattern in ("*.yml", "*.yaml"):
        for file_path in sorted(directory.glob(pattern)):
            if not file_path.is_file():
                continue
            definition = load_agent_family_definition_from_file(
                file_path,
                project=project,
                validate_prompt_refs=validate_prompt_refs,
            )
            if definition:
                definitions[definition.id] = definition
    return definitions


def _load_definitions_from_files(
    *,
    project: str | None,
    validate_prompt_refs: bool,
) -> dict[str, AgentFamilyDefinition]:
    definitions: dict[str, AgentFamilyDefinition] = {}
    search_paths = (
        get_xprompt_search_paths()
        if project is None
        else get_xprompt_search_paths(project)
    )
    for search_dir in reversed(search_paths):
        definitions.update(
            _load_definitions_from_dir(
                search_dir,
                project=project,
                validate_prompt_refs=validate_prompt_refs,
            )
        )
    return definitions


def _load_definitions_from_project_dir(
    project: str,
    *,
    validate_prompt_refs: bool,
) -> dict[str, AgentFamilyDefinition]:
    definitions: dict[str, AgentFamilyDefinition] = {}
    project_dirs = [
        source.path
        for source in resolve_xprompt_file_sources(project=project)
        if source.path is not None and source.scope == "home_project"
    ]
    for project_dir in reversed(project_dirs):
        definitions.update(
            _load_definitions_from_dir(
                project_dir,
                project=project,
                validate_prompt_refs=validate_prompt_refs,
            )
        )
    return definitions


def _load_definitions_from_project_workspace(
    project: str,
    *,
    validate_prompt_refs: bool,
) -> dict[str, AgentFamilyDefinition]:
    workspace_dir = get_known_project_workspaces().get(project)
    if workspace_dir is None:
        return {}
    definitions: dict[str, AgentFamilyDefinition] = {}
    project_dirs = [
        source.path
        for source in resolve_xprompt_file_sources(
            project_root=workspace_dir,
            project=project,
        )
        if source.path is not None and source.scope == "project"
    ]
    for xprompt_dir in reversed(project_dirs):
        definitions.update(
            _load_definitions_from_dir(
                xprompt_dir,
                project=project,
                validate_prompt_refs=validate_prompt_refs,
            )
        )
    return definitions


def _load_definitions_from_plugins(
    *,
    project: str | None,
    validate_prompt_refs: bool,
) -> dict[str, AgentFamilyDefinition]:
    if is_plugin_disabled("XPROMPTS"):
        return {}

    definitions: dict[str, AgentFamilyDefinition] = {}
    for module in discover_plugin_resources("sase_xprompts"):
        try:
            xprompts_dir = importlib.resources.files(module).joinpath("xprompts")
            entries = list(xprompts_dir.iterdir())  # type: ignore[union-attr]
        except (FileNotFoundError, OSError, TypeError, AttributeError):
            continue

        for entry in entries:
            entry_name: str = entry.name  # type: ignore[union-attr]
            if not (entry_name.endswith(".yml") or entry_name.endswith(".yaml")):
                continue
            try:
                text = entry.read_text(encoding="utf-8")  # type: ignore[union-attr]
            except (OSError, UnicodeDecodeError):
                continue

            tmpdir = Path(tempfile.mkdtemp(dir=get_sase_tmpdir()))
            tmp_path = tmpdir / entry_name
            try:
                tmp_path.write_text(text, encoding="utf-8")
                definition = load_agent_family_definition_from_file(
                    tmp_path,
                    project=project,
                    validate_prompt_refs=validate_prompt_refs,
                )
                if definition:
                    source = f"plugin:{module.__name__}/{entry_name}"
                    roles = tuple(
                        AgentFamilyRoleDefinition(
                            **{**asdict(role), "source_path": source}
                        )
                        for role in definition.roles
                    )
                    definitions[definition.id] = AgentFamilyDefinition(
                        id=definition.id,
                        version=definition.version,
                        extends=definition.extends,
                        roles=roles,
                        source_path=source,
                        config_hash=definition.config_hash,
                    )
            finally:
                tmp_path.unlink(missing_ok=True)
                tmpdir.rmdir()

    return definitions
