"""Shared bounded-read helpers for published-state repair observations."""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

from sase.agents_sync.inventory_io import (
    source_run_id as _source_run_id,
)
from sase.agents_sync.v2_io import MAX_JSON_BYTES
from sase.core.agent_run_state_wire import (
    AGENT_RUN_STATE_OBSERVATION_MALFORMED,
    AGENT_RUN_STATE_OBSERVATION_MISSING,
    AGENT_RUN_STATE_OBSERVATION_PRESENT,
    AGENT_RUN_STATE_OBSERVATION_UNREADABLE,
)

ACE_RUN_WORKFLOW = "ace-run"

_READ_HOOK: Callable[[Path], None] | None = None


def read_bounded_json(path: Path) -> tuple[str, dict[str, Any] | None]:
    """Read one JSON object using existing byte bounds.

    Returns ``(read_status, payload)``. Oversized or permission failures are
    unreadable; decode failures are malformed. Missing files stay missing.
    """

    if _READ_HOOK is not None:
        _READ_HOOK(path)
    try:
        if not path.is_file():
            return AGENT_RUN_STATE_OBSERVATION_MISSING, None
        if path.stat().st_size > MAX_JSON_BYTES:
            return AGENT_RUN_STATE_OBSERVATION_UNREADABLE, None
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return AGENT_RUN_STATE_OBSERVATION_MISSING, None
    except (OSError, PermissionError):
        return AGENT_RUN_STATE_OBSERVATION_UNREADABLE, None
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError):
        return AGENT_RUN_STATE_OBSERVATION_MALFORMED, None
    if not isinstance(payload, dict):
        return AGENT_RUN_STATE_OBSERVATION_MALFORMED, None
    return AGENT_RUN_STATE_OBSERVATION_PRESENT, payload


def derived_run_id(
    project_key: str, durable: str, workflow: str = ACE_RUN_WORKFLOW
) -> str:
    return _source_run_id(project_key, workflow, durable)
