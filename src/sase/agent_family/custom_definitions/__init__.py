"""File-backed custom agent-family definitions."""

from sase.agent_family.custom_definitions.discovery import (
    active_roles_after,
    get_all_agent_family_definitions,
)
from sase.agent_family.custom_definitions.loading import (
    is_agent_family_definition_mapping,
    load_agent_family_definition_from_file,
    load_agent_family_definition_from_mapping,
)
from sase.agent_family.custom_definitions.models import (
    STANDARD_EXTENDS_ID,
    AgentFamilyDefinition,
    AgentFamilyRoleDefinition,
    RoleAuto,
    RoleOnDone,
    RoleOnFailure,
)
from sase.agent_family.custom_definitions.validation import (
    role_definition_from_snapshot,
)

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
