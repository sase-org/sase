"""Reservation descriptor construction and transport."""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

from sase.agent.hijack._recovery_successor_common import (
    BOOTSTRAP_ACK_SCHEMA_VERSION,
    RECOVERY_DESCRIPTOR_ENV,
    RecoveryBootstrapError,
    RecoveryInheritanceError,
    RecoveryLineage,
    encode_recovery_lineage,
)


def build_recovery_descriptor(
    *,
    hijack_id: str,
    launch_identity: str,
    concrete_target: str,
    reserved_successor_name: str,
    project: str,
    workspace_dir: str,
    lineage: Mapping[str, Any] | RecoveryLineage,
    reserved_member: str = "",
    attach_plan: str = "",
    admission_request_id: str | None = None,
    admission_identity: str | None = None,
    workspace_num: int | None = None,
    expected_owner_pid: int | None = None,
    resolver_pid: int | None = None,
    resolver_process_identity_token: str | None = None,
    prompt_digest: str = "",
    attempt_revision: int = 0,
) -> dict[str, Any]:
    """Build one validated descriptor for a CAS reservation.

    The shape mirrors the core ``AgentHijackAdmissionDescriptorWire``:
    the prepared prompt digest and exact target, the reserved successor
    member/attach plan, the fixed project and workspace pair, the expected
    held owner, lineage, and the attempt identities. The executor persists
    one descriptor per reservation and threads it into the child through
    :data:`RECOVERY_DESCRIPTOR_ENV`; the child boot decodes it with
    :func:`decode_recovery_descriptor` and fails closed when it is missing.
    """
    if isinstance(lineage, RecoveryLineage):
        lineage_payload: str = encode_recovery_lineage(lineage)
    elif isinstance(lineage, Mapping):
        lineage_payload = encode_recovery_lineage(lineage)
    else:
        raise RecoveryInheritanceError(
            f"recovery descriptor requires a lineage mapping, got {type(lineage).__name__}"
        )
    return {
        "schema_version": BOOTSTRAP_ACK_SCHEMA_VERSION,
        "hijack_id": hijack_id,
        "launch_identity": launch_identity,
        "admission_request_id": admission_request_id,
        "admission_identity": admission_identity,
        "concrete_target": concrete_target,
        "reserved_successor_name": reserved_successor_name,
        "reserved_member": reserved_member,
        "attach_plan": attach_plan,
        "project": project,
        "workspace_num": workspace_num,
        "workspace_dir": workspace_dir,
        "expected_owner_pid": expected_owner_pid,
        "lineage": lineage_payload,
        "resolver_pid": resolver_pid,
        "resolver_process_identity_token": resolver_process_identity_token,
        "prompt_digest": prompt_digest,
        "attempt_revision": int(attempt_revision),
    }


def encode_recovery_descriptor(descriptor: Mapping[str, Any]) -> str:
    """Encode a reservation descriptor for transport in the child env."""
    return json.dumps(dict(descriptor), sort_keys=True)


def decode_recovery_descriptor(raw: str | None) -> dict[str, Any]:
    """Decode a reservation descriptor, failing closed when absent.

    Raises :class:`RecoveryBootstrapError` when the descriptor is missing,
    malformed, or names no usable reservation, so the child boot stops
    before the provider executes.
    """
    if not isinstance(raw, str) or not raw.strip():
        raise RecoveryBootstrapError(
            "missing_descriptor",
            f"recovery requires the reservation descriptor ({RECOVERY_DESCRIPTOR_ENV} is missing)",
        )
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RecoveryBootstrapError(
            "missing_descriptor",
            f"recovery descriptor payload is not valid JSON: {exc}",
        ) from exc
    if not isinstance(payload, Mapping) or not payload:
        raise RecoveryBootstrapError(
            "missing_descriptor",
            "recovery descriptor payload names no reservation",
        )
    descriptor = dict(payload)
    missing = [
        key
        for key in (
            "hijack_id",
            "launch_identity",
            "concrete_target",
            "reserved_successor_name",
            "project",
            "workspace_dir",
            "lineage",
        )
        if not descriptor.get(key)
    ]
    if missing:
        raise RecoveryBootstrapError(
            "missing_descriptor",
            "recovery descriptor is missing required fields: " + ", ".join(missing),
        )
    return descriptor
