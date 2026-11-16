"""Public facade for local-command trust management.

The private implementation modules separate checkout identity, store access,
and the human-only CLI while preserving this module's supported import path.
"""

from __future__ import annotations

from ._local_trust_checkout import (
    acknowledgment_target_path,
    logical_config_location_for_trust,
)
from ._local_trust_cli import (
    allow_local_commands,
    print_trust_status,
    revoke_local_commands,
)
from ._local_trust_membership import project_identity_for_config
from ._local_trust_store import (
    local_trust_store_snapshot,
    require_local_trust_human_terminal,
)
from ._local_trust_support import (
    LOCAL_COMMAND_TRUST_STORE_DIRECTORY,
    LOCAL_COMMAND_TRUST_STORE_FILENAME,
    LOCAL_COMMAND_TRUST_STORE_WIRE_SCHEMA_VERSION,
)
from .local_trust import (
    LOCAL_COMMAND_TRUST_POLICY_VERSION,
    LOCAL_COMMAND_TRUST_WIRE_SCHEMA_VERSION,
)

__all__ = [
    "LOCAL_COMMAND_TRUST_STORE_DIRECTORY",
    "LOCAL_COMMAND_TRUST_STORE_FILENAME",
    "LOCAL_COMMAND_TRUST_STORE_WIRE_SCHEMA_VERSION",
    "acknowledgment_target_path",
    "allow_local_commands",
    "local_trust_store_snapshot",
    "logical_config_location_for_trust",
    "print_trust_status",
    "project_identity_for_config",
    "require_local_trust_human_terminal",
    "revoke_local_commands",
]
