"""Archived marker fixtures for historical-reader tests.

Only ``write_legacy_handoff_marker`` remains: it seeds archived marker files to
prove historical readers and leftover-marker non-adoption. All executable
adoption goes through the staged entry points via
``tests._staged_handoff_adoption``.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def write_legacy_handoff_marker(
    marker: str, payload: dict[str, Any], *, artifacts_dir: str
) -> Path:
    """Seed an archived marker fixture without a production write protocol."""
    path = Path(artifacts_dir) / marker
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path
