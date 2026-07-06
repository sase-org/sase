"""Validation and parsing for custom agent-family definitions."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from typing import Any

from sase.agent_family.custom_definitions.models import (
    STANDARD_EXTENDS_ID,
    AgentFamilyDefinition,
    AgentFamilyRoleDefinition,
)
from sase.plan_chain import (
    AGENT_FAMILY_SEPARATOR,
    PLAN_CHAIN_CODER_SUFFIX,
    PLAN_CHAIN_COMMIT_SUFFIX,
    PLAN_CHAIN_EPIC_SUFFIX,
    PLAN_CHAIN_LEGEND_SUFFIX,
    PLAN_CHAIN_PLAN_SUFFIX,
    PLAN_CHAIN_QUESTION_SUFFIX,
)

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
    "label",
    "done_label",
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
_DISPLAY_LABEL_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 _/-]*$")
_DISPLAY_LABEL_MAX_LEN = 24


class AgentFamilyDefinitionError(ValueError):
    """Raised when an ``agent_family`` YAML definition is invalid."""


def parse_agent_family_definition(
    data: Mapping[str, object],
    source_path: str,
    *,
    project: str | None,
    validate_prompt_refs: bool,
) -> AgentFamilyDefinition:
    schema_version = data.get("schema_version")
    if schema_version != 1:
        raise AgentFamilyDefinitionError("schema_version must be 1")
    definition_id = _required_role_like_id(data.get("id"), "id")
    version = _positive_int(data.get("version"), "version")
    extends = str(data.get("extends") or STANDARD_EXTENDS_ID)
    if extends != STANDARD_EXTENDS_ID:
        raise AgentFamilyDefinitionError(
            f"extends must be {STANDARD_EXTENDS_ID!r}, got {extends!r}"
        )
    roles_data = data.get("roles")
    if not isinstance(roles_data, Mapping) or not roles_data:
        raise AgentFamilyDefinitionError("roles must be a non-empty mapping")

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
            label=_optional_display_label(snapshot.get("label"), "label"),
            done_label=_optional_display_label(
                snapshot.get("done_label"), "done_label"
            ),
            reserved=reserved if isinstance(reserved, Mapping) else {},
        )
    except (KeyError, TypeError, ValueError):
        return None


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
        raise AgentFamilyDefinitionError(f"role {role_id!r} must be a mapping")
    unknown = set(raw_role) - _ROLE_KEYS
    if unknown:
        keys = ", ".join(sorted(str(key) for key in unknown))
        raise AgentFamilyDefinitionError(f"role {role_id!r} has unknown keys: {keys}")
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
    label = _optional_display_label(raw_role.get("label"), f"role {role_id!r} label")
    done_label = _optional_display_label(
        raw_role.get("done_label"),
        f"role {role_id!r} done_label",
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
        label=label,
        done_label=done_label,
        reserved=reserved,
    )


def _required_role_like_id(value: object, field_name: str) -> str:
    text = _required_str(value, field_name)
    if not _ROLE_ID_RE.fullmatch(text):
        raise AgentFamilyDefinitionError(
            f"{field_name} {text!r} must use letters, numbers, and underscores"
        )
    return text


def _required_str(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise AgentFamilyDefinitionError(f"{field_name} is required")
    return value.strip()


def _positive_int(value: object, field_name: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise AgentFamilyDefinitionError(f"{field_name} must be a positive integer")
    return value


def _literal_value(
    value: object,
    allowed: set[str],
    field_name: str,
) -> Any:
    if not isinstance(value, str) or value not in allowed:
        choices = " | ".join(sorted(allowed))
        raise AgentFamilyDefinitionError(f"{field_name} must be one of: {choices}")
    return value


def _optional_bool(value: object, field_name: str) -> bool:
    if isinstance(value, bool):
        return value
    raise AgentFamilyDefinitionError(f"{field_name} must be true or false")


def _optional_display_label(value: object, field_name: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise AgentFamilyDefinitionError(f"{field_name} must be a string")
    text = value.strip()
    if not text:
        raise AgentFamilyDefinitionError(f"{field_name} must not be empty")
    if len(text) > _DISPLAY_LABEL_MAX_LEN:
        raise AgentFamilyDefinitionError(
            f"{field_name} must be {_DISPLAY_LABEL_MAX_LEN} characters or fewer"
        )
    if not _DISPLAY_LABEL_RE.fullmatch(text):
        raise AgentFamilyDefinitionError(
            f"{field_name} must use letters, numbers, spaces, _, -, or /"
        )
    return text


def _parse_suffix(value: object, role_id: str) -> str:
    suffix = f"{AGENT_FAMILY_SEPARATOR}{role_id}" if value is None else str(value)
    if suffix.startswith(".") or (
        suffix.startswith("-") and not suffix.startswith(AGENT_FAMILY_SEPARATOR)
    ):
        raise AgentFamilyDefinitionError(
            f"role {role_id!r} suffix must use canonical '--' spelling"
        )
    if not suffix.startswith(AGENT_FAMILY_SEPARATOR):
        raise AgentFamilyDefinitionError(
            f"role {role_id!r} suffix must start with '--'"
        )
    if not _CANONICAL_SUFFIX_RE.fullmatch(suffix):
        raise AgentFamilyDefinitionError(
            f"role {role_id!r} suffix must use letters, numbers, and underscores"
        )
    if suffix in _RESERVED_SUFFIXES:
        raise AgentFamilyDefinitionError(
            f"role {role_id!r} suffix {suffix!r} is reserved by the standard chain"
        )
    return suffix


def _parse_placement(value: object, role_id: str) -> str:
    if not isinstance(value, Mapping):
        raise AgentFamilyDefinitionError(
            f"role {role_id!r} placement must be a mapping"
        )
    after = value.get("after")
    if not isinstance(after, str) or not after.strip():
        raise AgentFamilyDefinitionError(
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
        raise AgentFamilyDefinitionError(
            f"role {role_id!r} prompt_template must name an xprompt reference"
        )
    from sase.xprompt.loader import get_all_prompts

    if prompt_name not in get_all_prompts(project=project):
        raise AgentFamilyDefinitionError(
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
