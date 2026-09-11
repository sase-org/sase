"""Handoff checkpoint publication for continuation capture."""

from __future__ import annotations

from collections.abc import Mapping
import os
import time
from typing import Any

from sase.core.continuation_wire import CONTINUATION_WIRE_SCHEMA_VERSION

from ._storage import (
    continuation_root,
    json_safe,
    local_ref,
    safe_identifier,
    sha_json,
    write_json_atomic,
    record_capture_error,
)


def publish_handoff_checkpoint_best_effort(
    artifacts_dir: str | os.PathLike[str] | None,
    *,
    checkpoint_kind: str,
    payload: Mapping[str, Any],
) -> str | None:
    """Best-effort wrapper for handoff checkpoint publication."""

    if artifacts_dir is None:
        return None
    try:
        return publish_handoff_checkpoint(
            artifacts_dir,
            checkpoint_kind=checkpoint_kind,
            payload=payload,
        )
    except Exception as exc:
        record_capture_error(artifacts_dir, f"checkpoint:{checkpoint_kind}", exc)
        return None


def publish_handoff_checkpoint(
    artifacts_dir: str | os.PathLike[str],
    *,
    checkpoint_kind: str,
    payload: Mapping[str, Any],
) -> str:
    """Persist a content-addressed checkpoint and return its local ref."""

    root = continuation_root(artifacts_dir)
    root.mkdir(parents=True, exist_ok=True)
    checkpoint_payload = {
        "schema_version": CONTINUATION_WIRE_SCHEMA_VERSION,
        "kind": checkpoint_kind,
        "payload": json_safe(payload),
        "recorded_at_epoch": time.time(),
    }
    digest = sha_json(checkpoint_payload)
    filename = f"{safe_identifier(checkpoint_kind)}-{digest[:16]}.json"
    path = root / "checkpoints" / filename
    write_json_atomic(path, checkpoint_payload)
    return local_ref("checkpoints", filename)


__all__ = [
    "publish_handoff_checkpoint",
    "publish_handoff_checkpoint_best_effort",
]
