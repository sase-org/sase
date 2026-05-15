"""Shared helpers for notification modal response files."""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any


def write_workflow_action_response(
    response_path: Path,
    response_data: dict[str, object],
    *,
    action_kind: str,
    notification_id: str,
    default: Callable[[Any], Any] | None = None,
) -> None:
    _ = (action_kind, notification_id)
    with response_path.open("x", encoding="utf-8") as f:
        json.dump(response_data, f, indent=2, default=default)
        f.write("\n")
