"""Public facade for run-agent directive metadata.

This module preserves the historical
``sase.axe.run_agent_directive_metadata`` import surface while the
implementation lives in smaller focused modules.
"""

from sase.axe.run_agent_directive_metadata_build import build_agent_meta
from sase.axe.run_agent_directive_metadata_inputs import (
    DEFAULT_QUEUE_WEIGHT,
    EPIC_WORK_ENV_METADATA_NAMES,
    AgentMetadataInputs,
)
from sase.axe.run_agent_directive_metadata_preserved import (
    consume_epic_clan_summary_script_from_env,
    epic_work_environment_from_metadata,
    epic_work_metadata_from_env,
    export_agent_tab_env,
    preserved_agent_metadata,
    session_root_tab,
)

__all__ = [
    "AgentMetadataInputs",
    "DEFAULT_QUEUE_WEIGHT",
    "EPIC_WORK_ENV_METADATA_NAMES",
    "build_agent_meta",
    "consume_epic_clan_summary_script_from_env",
    "epic_work_environment_from_metadata",
    "epic_work_metadata_from_env",
    "export_agent_tab_env",
    "preserved_agent_metadata",
    "session_root_tab",
]
