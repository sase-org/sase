"""Wire encoding and decoding for durable completion-failure facts.

The codec is shared by every Python reader of the bead wire — the Rust
outcome dicts decoded by :mod:`sase.core.bead_wire` and the stranded-work
collector facts — so a fact cannot mean one thing in one surface and
something else in another. The facts stay authoritative in the Rust event
store (encoding lives in sase-core); the compatibility SQLite mirror does
not carry these columns (its rebuild migrations are Rust-owned), and reads
go through the Rust facade.

Key order mirrors ``BeadCompletionFailureWire`` in sase-core.
"""

from __future__ import annotations

from typing import Any

from sase.bead.model import BeadCompletionFailure


def completion_failure_from_dict(value: object) -> BeadCompletionFailure | None:
    """Decode a completion-failure fact, tolerating absence but not junk."""
    if value is None:
        return None
    if not isinstance(value, dict):
        raise ValueError("completion failure must be a mapping")
    evidence = value.get("evidence_locations")
    return BeadCompletionFailure(
        close_event_id=str(value.get("close_event_id", "")),
        run_id=str(value.get("run_id", "")),
        agent_name=str(value.get("agent_name", "")),
        artifact_dir=str(value.get("artifact_dir", "")),
        failed_at=str(value.get("failed_at", "")),
        failure_code=str(value.get("failure_code", "")),
        evidence_locations=tuple(
            str(location) for location in evidence if location is not None
        )
        if isinstance(evidence, list)
        else (),
    )


def completion_failure_to_dict(failure: BeadCompletionFailure) -> dict[str, Any]:
    """Encode a completion-failure fact in sase-core wire field order."""
    return {
        "close_event_id": failure.close_event_id,
        "run_id": failure.run_id,
        "agent_name": failure.agent_name,
        "artifact_dir": failure.artifact_dir,
        "failed_at": failure.failed_at,
        "evidence_locations": list(failure.evidence_locations),
        "failure_code": failure.failure_code,
    }


__all__ = [
    "completion_failure_from_dict",
    "completion_failure_to_dict",
]
