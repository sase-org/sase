"""Shared artifact logging for provider stranded-command guards."""

from __future__ import annotations

import json
import os
import time
from pathlib import Path


def log_wait_guard(reason: str, cycle: int) -> None:
    """Append one stranded-command guard firing to the artifacts directory."""
    artifacts_dir = os.environ.get("SASE_ARTIFACTS_DIR")
    if not artifacts_dir:
        return
    log_path = Path(artifacts_dir) / "wait_guard_log.jsonl"
    try:
        with open(log_path, "a", encoding="utf-8") as file:
            json.dump(
                {"reason": reason, "timestamp": time.time(), "cycle": cycle},
                file,
            )
            file.write("\n")
    except OSError:
        pass
