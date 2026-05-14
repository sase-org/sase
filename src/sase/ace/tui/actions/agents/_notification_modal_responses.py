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
    from sase.xprompt.workflow_daemon_writes import write_action_response_once

    def direct_writer() -> None:
        with response_path.open("x", encoding="utf-8") as f:
            json.dump(response_data, f, indent=2, default=default)
            f.write("\n")

    write_action_response_once(
        response_path,
        response_data,
        action_kind=action_kind,
        notification_id=notification_id,
        direct_writer=direct_writer,
    )
