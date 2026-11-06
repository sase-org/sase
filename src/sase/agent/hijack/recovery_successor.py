"""Strict recovery successor preparation and mandatory inheritance.

This module preserves the historical public import path while implementation
lives in focused private modules for lineage, inheritance, bootstrap, and launch.
"""

from __future__ import annotations

from sase.agent.hijack._recovery_successor_common import (
    BOOTSTRAP_ACK_SCHEMA_VERSION,
    HIJACK_LINEAGE_META_KEY,
    NON_INHERITABLE_VERDICT_KEYS,
    RECOVERY_ACK_FILENAME,
    RECOVERY_DESCRIPTOR_ENV,
    RECOVERY_LINEAGE_ENV,
    RECOVERY_LINEAGE_META_KEY,
    RECOVERY_STRICT_ENV,
    RecoveryInheritanceError,
    RecoveryLineage,
    decode_recovery_lineage,
)
from sase.agent.hijack._recovery_successor_descriptor import (
    build_recovery_descriptor,
    decode_recovery_descriptor,
    encode_recovery_descriptor,
)
from sase.agent.hijack._recovery_successor_bootstrap_observation import (
    collect_bootstrap_observation,
)
from sase.agent.hijack._recovery_successor_bootstrap_validation import (
    enforce_recovery_bootstrap,
)
from sase.agent.hijack._recovery_successor_inheritance import (
    read_recovery_ack,
    require_recovery_inheritance,
    rollback_recovery_preparation,
    write_recovery_ack,
)
from sase.agent.hijack._recovery_successor_launch import (
    prepare_recovery_successor,
    spawn_recovery_successor,
)

__all__ = [
    "BOOTSTRAP_ACK_SCHEMA_VERSION",
    "HIJACK_LINEAGE_META_KEY",
    "NON_INHERITABLE_VERDICT_KEYS",
    "RECOVERY_ACK_FILENAME",
    "RECOVERY_DESCRIPTOR_ENV",
    "RECOVERY_LINEAGE_ENV",
    "RECOVERY_LINEAGE_META_KEY",
    "RECOVERY_STRICT_ENV",
    "RecoveryInheritanceError",
    "RecoveryLineage",
    "build_recovery_descriptor",
    "collect_bootstrap_observation",
    "decode_recovery_descriptor",
    "decode_recovery_lineage",
    "encode_recovery_descriptor",
    "enforce_recovery_bootstrap",
    "prepare_recovery_successor",
    "read_recovery_ack",
    "require_recovery_inheritance",
    "rollback_recovery_preparation",
    "spawn_recovery_successor",
    "write_recovery_ack",
]
