"""Compatibility facade for durable agent-name registry mutations."""

from sase.agent.names._registry_agent_mutations import (
    claim_registered_name as claim_registered_name,
    delete_registered_name as delete_registered_name,
    release_planned_registered_name as release_planned_registered_name,
    reserve_registered_name as reserve_registered_name,
)
from sase.agent.names._registry_group_mutations import (
    claim_registered_clan_name as claim_registered_clan_name,
    convert_registered_agent_to_family as convert_registered_agent_to_family,
    release_planned_registered_clan_name as release_planned_registered_clan_name,
    reserve_registered_clan_name as reserve_registered_clan_name,
)
from sase.agent.names._registry_mutation_support import (
    RegistryMutationOperations as RegistryMutationOperations,
)
from sase.agent.names._registry_template_mutations import (
    reserve_registered_template_name as reserve_registered_template_name,
    reserve_registered_template_names as reserve_registered_template_names,
)

__all__ = [
    "RegistryMutationOperations",
    "claim_registered_clan_name",
    "claim_registered_name",
    "convert_registered_agent_to_family",
    "delete_registered_name",
    "release_planned_registered_clan_name",
    "release_planned_registered_name",
    "reserve_registered_clan_name",
    "reserve_registered_name",
    "reserve_registered_template_name",
    "reserve_registered_template_names",
]
