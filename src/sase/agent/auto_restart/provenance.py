"""Provenance for agents relaunched by update-skew auto-restart.

The healer passes ``SASE_AUTO_RESTART_PROVENANCE`` (inline JSON) through
the force-reuse plan's segment env. At bootstrap the runner consumes it
into ``agent_meta["auto_restart"]`` so the replacement's identity header
can render the ``↻ Auto-restarted after sase update …`` block. The value
survives refresh re-execs through the preserved-metadata path.
"""

from __future__ import annotations

import json
import os
from typing import Any

PROVENANCE_ENV = "SASE_AUTO_RESTART_PROVENANCE"


def read_auto_restart_provenance() -> dict[str, Any] | None:
    """Return the provenance payload from the environment, if present."""
    raw = os.environ.get(PROVENANCE_ENV)
    if not raw:
        return None
    try:
        payload = json.loads(raw)
    except ValueError:
        return None
    if not isinstance(payload, dict):
        return None
    return payload


def provenance_segment_env(provenance: dict[str, Any]) -> dict[str, str]:
    """Render the provenance payload as a segment-env overlay."""
    return {PROVENANCE_ENV: json.dumps(provenance, sort_keys=True)}


__all__ = [
    "PROVENANCE_ENV",
    "provenance_segment_env",
    "read_auto_restart_provenance",
]
