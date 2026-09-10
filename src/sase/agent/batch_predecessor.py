"""Prompt-stack predecessor context shared between launcher and runner."""

from __future__ import annotations

from collections.abc import Mapping, MutableMapping
import json
import os
from typing import Any

from sase.core.agent_launch_wire import (
    BATCH_PREDECESSOR_CONTEXT_SCHEMA_VERSION,
    BatchPredecessorContextWire,
    agent_launch_wire_to_json_dict,
    batch_predecessor_context_from_dict,
)

SASE_AGENT_PREDECESSOR_CONTEXT_ENV = "SASE_AGENT_PREDECESSOR_CONTEXT"


def batch_predecessor_context(
    *,
    project_name: str,
    timestamp: str,
    artifact_dir: str,
    name: str | None,
) -> BatchPredecessorContextWire:
    """Build a schema-versioned predecessor context payload."""

    return BatchPredecessorContextWire(
        schema_version=BATCH_PREDECESSOR_CONTEXT_SCHEMA_VERSION,
        project_name=project_name,
        timestamp=timestamp,
        artifact_dir=artifact_dir,
        name=name,
    )


def encode_batch_predecessor_context(
    context: BatchPredecessorContextWire,
) -> str:
    """Serialize a predecessor context for launch environment transport."""

    return json.dumps(
        agent_launch_wire_to_json_dict(context),
        separators=(",", ":"),
        sort_keys=True,
    )


def _decode_batch_predecessor_context(value: str) -> BatchPredecessorContextWire:
    """Deserialize a predecessor context from launch environment transport."""

    payload = json.loads(value)
    if not isinstance(payload, dict):
        raise ValueError("context payload must be an object")
    return batch_predecessor_context_from_dict(payload)


def consume_batch_predecessor_context_from_env(
    env: MutableMapping[str, str] | None = None,
) -> BatchPredecessorContextWire | None:
    """Pop and decode the predecessor context from *env* or ``os.environ``."""

    target = os.environ if env is None else env
    raw = target.pop(SASE_AGENT_PREDECESSOR_CONTEXT_ENV, None)
    if not raw:
        return None
    try:
        return _decode_batch_predecessor_context(raw)
    except (json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
        raise RuntimeError(
            f"Invalid {SASE_AGENT_PREDECESSOR_CONTEXT_ENV}: {exc}"
        ) from exc


def preserved_batch_predecessor_context(
    preserved: Mapping[str, Any],
) -> BatchPredecessorContextWire | None:
    """Return the persisted predecessor context from runner metadata, if present."""

    payload = preserved.get("batch_predecessor_context")
    if not isinstance(payload, Mapping):
        return None
    return batch_predecessor_context_from_dict(dict(payload))
