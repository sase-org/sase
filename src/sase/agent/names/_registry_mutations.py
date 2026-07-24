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
from sase.agent.names._registry_import_mutations import (
    ImportedV2RegistryClaim as ImportedV2RegistryClaim,
    claim_imported_registered_name as claim_imported_registered_name,
    claim_imported_registered_name_v2 as claim_imported_registered_name_v2,
    claim_imported_registered_names_v2 as claim_imported_registered_names_v2,
    preflight_imported_registered_names_v2 as preflight_imported_registered_names_v2,
)
from sase.agent.names._registry_mutation_support import (
    RegistryMutationOperations as RegistryMutationOperations,
)
from sase.agent.names._registry_template_mutations import (
    reserve_registered_template_name as reserve_registered_template_name,
    reserve_registered_template_names as reserve_registered_template_names,
)

__all__ = [
    "ImportedV2RegistryClaim",
    "RegistryMutationOperations",
    "claim_imported_registered_name",
    "claim_imported_registered_name_v2",
    "claim_imported_registered_names_v2",
    "claim_registered_clan_name",
    "claim_registered_name",
    "convert_registered_agent_to_family",
    "delete_registered_name",
    "preflight_imported_registered_names_v2",
    "release_planned_registered_clan_name",
    "release_planned_registered_name",
    "reserve_registered_clan_name",
    "reserve_registered_name",
    "reserve_registered_template_name",
    "reserve_registered_template_names",
]
