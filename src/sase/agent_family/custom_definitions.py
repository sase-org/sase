"""File-backed custom agent-family definitions."""

from __future__ import annotations

import hashlib
import importlib.resources
import json
import logging
import re
import tempfile
from collections.abc import Mapping
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Literal

import yaml  # type: ignore[import-untyped]

from sase.core.paths import get_sase_tmpdir
from sase.main.plugin_discovery import discover_plugin_resources, is_plugin_disabled
from sase.plan_chain import (
    AGENT_FAMILY_SEPARATOR,
    PLAN_CHAIN_CODER_SUFFIX,
    PLAN_CHAIN_COMMIT_SUFFIX,
    PLAN_CHAIN_EPIC_SUFFIX,
    PLAN_CHAIN_LEGEND_SUFFIX,
    PLAN_CHAIN_PLAN_SUFFIX,
    PLAN_CHAIN_QUESTION_SUFFIX,
)
from sase.xprompt.load_issues import record_load_issue
from sase.xprompt.loader import (
    detect_project,
    get_known_project_workspaces,
    get_sase_package_xprompts_dir,
    get_xprompt_search_paths,
)

log = logging.getLogger(__name__)

STANDARD_EXTENDS_ID = "standard_plan_chain"

type RoleOnDone = Literal["re_review", "continue", "terminate"]
type RoleOnFailure = Literal["notify_and_continue", "notify_and_stop"]
type RoleAuto = Literal["run", "skip"]

_ROLE_ID_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]*$")
_CANONICAL_SUFFIX_RE = re.compile(r"^--[A-Za-z0-9_]+$")
_RESERVED_SUFFIXES = {
    PLAN_CHAIN_PLAN_SUFFIX,
    PLAN_CHAIN_QUESTION_SUFFIX,
    PLAN_CHAIN_CODER_SUFFIX,
    PLAN_CHAIN_EPIC_SUFFIX,
    PLAN_CHAIN_LEGEND_SUFFIX,
    PLAN_CHAIN_COMMIT_SUFFIX,
}
_ROLE_KEYS = {
    "suffix",
    "prompt_template",
    "placement",
    "on_done",
    "max_visits",
    "on_failure",
    "auto",
    "default",
    # Reserved for the Phase 8 delegated-budget design. These are accepted
    # and snapshotted but intentionally not interpreted in Phase 5.
    "delegated_budget",
    "delegated_budgets",
}
_RESERVED_ROLE_KEYS = {"delegated_budget", "delegated_budgets"}


class _AgentFamilyDefinitionError(ValueError):
    """Raised when an ``agent_family`` YAML definition is invalid."""


@dataclass(frozen=True)
class AgentFamilyRoleDefinition:
    """A custom role loaded from an ``agent_family`` YAML file."""

    id: str
    suffix: str
    prompt_template: str
    placement_after: str
    on_done: RoleOnDone
    max_visits: int
    on_failure: RoleOnFailure
    auto: RoleAuto
    default_enabled: bool
    config_id: str
    config_version: int
    config_hash: str
    source_path: str
    reserved: Mapping[str, object] = field(default_factory=dict)

    def as_snapshot(self) -> dict[str, object]:
        return {
            "id": self.id,
            "suffix": self.suffix,
            "prompt_template": self.prompt_template,
            "placement_after": self.placement_after,
            "on_done": self.on_done,
            "max_visits": self.max_visits,
            "on_failure": self.on_failure,
            "auto": self.auto,
            "default": self.default_enabled,
            "config_id": self.config_id,
            "config_version": self.config_version,
            "config_hash": self.config_hash,
            "source_path": self.source_path,
            "reserved": dict(self.reserved),
        }


@dataclass(frozen=True)
class AgentFamilyDefinition:
    """A validated ``kind: agent_family`` definition."""

    id: str
    version: int
    extends: str
    roles: tuple[AgentFamilyRoleDefinition, ...]
    source_path: str
    config_hash: str


def role_definition_from_snapshot(
    snapshot: Mapping[str, object],
) -> AgentFamilyRoleDefinition | None:
    """Rebuild a custom role from persisted artifact metadata."""

    try:
        reserved = snapshot.get("reserved")
        return AgentFamilyRoleDefinition(
            id=str(snapshot["id"]),
            suffix=str(snapshot["suffix"]),
            prompt_template=str(snapshot["prompt_template"]),
            placement_after=str(snapshot["placement_after"]),
            on_done=_literal_value(
                snapshot["on_done"],
                {"re_review", "continue", "terminate"},
                "on_done",
            ),
            max_visits=_positive_int(snapshot["max_visits"], "max_visits"),
            on_failure=_literal_value(
                snapshot["on_failure"],
                {"notify_and_continue", "notify_and_stop"},
                "on_failure",
            ),
            auto=_literal_value(snapshot["auto"], {"run", "skip"}, "auto"),
            default_enabled=_optional_bool(snapshot.get("default", False), "default"),
            config_id=str(snapshot["config_id"]),
            config_version=_positive_int(snapshot["config_version"], "config_version"),
            config_hash=str(snapshot["config_hash"]),
            source_path=str(snapshot.get("source_path") or "<snapshot>"),
            reserved=reserved if isinstance(reserved, Mapping) else {},
        )
    except (KeyError, TypeError, ValueError):
        return None


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
        return _parse_agent_family_definition(
            data,
            source_path,
            project=project,
            validate_prompt_refs=validate_prompt_refs,
        )
    except _AgentFamilyDefinitionError as exc:
        record_load_issue(source_path, exc, kind="agent_family")
        return None


def is_agent_family_definition_mapping(data: object) -> bool:
    """Return whether *data* is a top-level ``kind: agent_family`` mapping."""

    return isinstance(data, Mapping) and data.get("kind") == "agent_family"


def _parse_agent_family_definition(
    data: Mapping[str, object],
    source_path: str,
    *,
    project: str | None,
    validate_prompt_refs: bool,
) -> AgentFamilyDefinition:
    schema_version = data.get("schema_version")
    if schema_version != 1:
        raise _AgentFamilyDefinitionError("schema_version must be 1")
    definition_id = _required_role_like_id(data.get("id"), "id")
    version = _positive_int(data.get("version"), "version")
    extends = str(data.get("extends") or STANDARD_EXTENDS_ID)
    if extends != STANDARD_EXTENDS_ID:
        raise _AgentFamilyDefinitionError(
            f"extends must be {STANDARD_EXTENDS_ID!r}, got {extends!r}"
        )
    roles_data = data.get("roles")
    if not isinstance(roles_data, Mapping) or not roles_data:
        raise _AgentFamilyDefinitionError("roles must be a non-empty mapping")

    hash_payload = {
        "schema_version": schema_version,
        "id": definition_id,
        "version": version,
        "extends": extends,
        "roles": roles_data,
    }
    config_hash = hashlib.sha256(
        json.dumps(hash_payload, sort_keys=True, default=str).encode("utf-8")
    ).hexdigest()

    roles = tuple(
        _parse_role(
            role_id=str(role_id),
            raw_role=raw_role,
            definition_id=definition_id,
            definition_version=version,
            config_hash=config_hash,
            source_path=source_path,
            project=project,
            validate_prompt_refs=validate_prompt_refs,
        )
        for role_id, raw_role in roles_data.items()
    )
    return AgentFamilyDefinition(
        id=definition_id,
        version=version,
        extends=extends,
        roles=roles,
        source_path=source_path,
        config_hash=config_hash,
    )


def _parse_role(
    *,
    role_id: str,
    raw_role: object,
    definition_id: str,
    definition_version: int,
    config_hash: str,
    source_path: str,
    project: str | None,
    validate_prompt_refs: bool,
) -> AgentFamilyRoleDefinition:
    role_id = _required_role_like_id(role_id, "role id")
    if not isinstance(raw_role, Mapping):
        raise _AgentFamilyDefinitionError(f"role {role_id!r} must be a mapping")
    unknown = set(raw_role) - _ROLE_KEYS
    if unknown:
        keys = ", ".join(sorted(str(key) for key in unknown))
        raise _AgentFamilyDefinitionError(f"role {role_id!r} has unknown keys: {keys}")
    suffix = _parse_suffix(raw_role.get("suffix"), role_id)
    prompt_template = _required_str(
        raw_role.get("prompt_template"),
        f"role {role_id!r} prompt_template",
    )
    if validate_prompt_refs:
        _validate_prompt_template_ref(
            prompt_template,
            source_path=source_path,
            project=project,
            role_id=role_id,
        )
    placement_after = _parse_placement(raw_role.get("placement"), role_id)
    on_done = _literal_value(
        raw_role.get("on_done"),
        {"re_review", "continue", "terminate"},
        f"role {role_id!r} on_done",
    )
    on_failure = _literal_value(
        raw_role.get("on_failure"),
        {"notify_and_continue", "notify_and_stop"},
        f"role {role_id!r} on_failure",
    )
    auto = _literal_value(
        raw_role.get("auto"),
        {"run", "skip"},
        f"role {role_id!r} auto",
    )
    default_enabled = _optional_bool(
        raw_role.get("default", False),
        f"role {role_id!r} default",
    )
    max_visits = _positive_int(
        raw_role.get("max_visits", 3),
        f"role {role_id!r} max_visits",
    )
    reserved = {
        str(key): value for key, value in raw_role.items() if key in _RESERVED_ROLE_KEYS
    }
    return AgentFamilyRoleDefinition(
        id=role_id,
        suffix=suffix,
        prompt_template=prompt_template,
        placement_after=placement_after,
        on_done=on_done,
        max_visits=max_visits,
        on_failure=on_failure,
        auto=auto,
        default_enabled=default_enabled,
        config_id=definition_id,
        config_version=definition_version,
        config_hash=config_hash,
        source_path=source_path,
        reserved=reserved,
    )


def _required_role_like_id(value: object, field_name: str) -> str:
    text = _required_str(value, field_name)
    if not _ROLE_ID_RE.fullmatch(text):
        raise _AgentFamilyDefinitionError(
            f"{field_name} {text!r} must use letters, numbers, and underscores"
        )
    return text


def _required_str(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise _AgentFamilyDefinitionError(f"{field_name} is required")
    return value.strip()


def _positive_int(value: object, field_name: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise _AgentFamilyDefinitionError(f"{field_name} must be a positive integer")
    return value


def _literal_value(
    value: object,
    allowed: set[str],
    field_name: str,
) -> Any:
    if not isinstance(value, str) or value not in allowed:
        choices = " | ".join(sorted(allowed))
        raise _AgentFamilyDefinitionError(f"{field_name} must be one of: {choices}")
    return value


def _optional_bool(value: object, field_name: str) -> bool:
    if isinstance(value, bool):
        return value
    raise _AgentFamilyDefinitionError(f"{field_name} must be true or false")


def _parse_suffix(value: object, role_id: str) -> str:
    suffix = f"{AGENT_FAMILY_SEPARATOR}{role_id}" if value is None else str(value)
    if suffix.startswith(".") or (
        suffix.startswith("-") and not suffix.startswith(AGENT_FAMILY_SEPARATOR)
    ):
        raise _AgentFamilyDefinitionError(
            f"role {role_id!r} suffix must use canonical '--' spelling"
        )
    if not suffix.startswith(AGENT_FAMILY_SEPARATOR):
        raise _AgentFamilyDefinitionError(
            f"role {role_id!r} suffix must start with '--'"
        )
    if not _CANONICAL_SUFFIX_RE.fullmatch(suffix):
        raise _AgentFamilyDefinitionError(
            f"role {role_id!r} suffix must use letters, numbers, and underscores"
        )
    if suffix in _RESERVED_SUFFIXES:
        raise _AgentFamilyDefinitionError(
            f"role {role_id!r} suffix {suffix!r} is reserved by the standard chain"
        )
    return suffix


def _parse_placement(value: object, role_id: str) -> str:
    if not isinstance(value, Mapping):
        raise _AgentFamilyDefinitionError(
            f"role {role_id!r} placement must be a mapping"
        )
    after = value.get("after")
    if not isinstance(after, str) or not after.strip():
        raise _AgentFamilyDefinitionError(
            f"role {role_id!r} placement.after is required"
        )
    return after.strip()


def _validate_prompt_template_ref(
    prompt_template: str,
    *,
    source_path: str,
    project: str | None,
    role_id: str,
) -> None:
    prompt_name = _prompt_reference_name(prompt_template)
    if not prompt_name:
        raise _AgentFamilyDefinitionError(
            f"role {role_id!r} prompt_template must name an xprompt reference"
        )
    from sase.xprompt.loader import get_all_prompts

    if prompt_name not in get_all_prompts(project=project):
        raise _AgentFamilyDefinitionError(
            f"role {role_id!r} references unknown xprompt {prompt_name!r}"
        )


def _prompt_reference_name(prompt_template: str) -> str:
    text = prompt_template.strip()
    if text.startswith("#"):
        text = text[1:]
    for separator in (":", "(", " ", "\n", "\t"):
        if separator in text:
            text = text.split(separator, 1)[0]
    return text.strip()


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
    for search_dir in reversed(get_xprompt_search_paths()):
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
    project_dir = Path.home() / ".config" / "sase" / "xprompts" / project
    return _load_definitions_from_dir(
        project_dir,
        project=project,
        validate_prompt_refs=validate_prompt_refs,
    )


def _load_definitions_from_project_workspace(
    project: str,
    *,
    validate_prompt_refs: bool,
) -> dict[str, AgentFamilyDefinition]:
    workspace_dir = get_known_project_workspaces().get(project)
    if workspace_dir is None:
        return {}
    definitions: dict[str, AgentFamilyDefinition] = {}
    for xprompt_dir in (workspace_dir / ".xprompts", workspace_dir / "xprompts"):
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


__all__ = [
    "AgentFamilyDefinition",
    "AgentFamilyRoleDefinition",
    "RoleAuto",
    "RoleOnDone",
    "RoleOnFailure",
    "STANDARD_EXTENDS_ID",
    "active_roles_after",
    "get_all_agent_family_definitions",
    "is_agent_family_definition_mapping",
    "load_agent_family_definition_from_file",
    "load_agent_family_definition_from_mapping",
    "role_definition_from_snapshot",
]
