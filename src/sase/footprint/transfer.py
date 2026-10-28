"""Weekly export pack building and import file parsing for Footprint.

Off-hot-path helpers used only by the ``sase footprint export`` and
``sase footprint import`` handlers. The Rust core owns pack projection,
validation, and the ledger merge; this module only builds the export
request, renders packs as canonical JSON Lines, and parses pack files.
"""

from __future__ import annotations

import json
import sys
from datetime import date
from pathlib import Path
from typing import Any


def build_export_request(weeks: int | None) -> dict[str, Any]:
    """Build a ``footprint_export`` request for the local ledger."""

    from sase import __version__
    from sase.footprint.paths import ledger_path

    platform = sys.platform
    if platform.startswith("linux"):
        os_name = "linux"
    elif platform == "darwin" or platform.startswith("darwin"):
        os_name = "darwin"
    else:
        raise ValueError("Footprint export supports linux and darwin only")
    parts = __version__.split(".")
    sase_minor = ".".join(parts[:2]) if len(parts) >= 2 else __version__
    request: dict[str, Any] = {
        "store_path": ledger_path(),
        "today": date.today().isoformat(),
        "sase": sase_minor,
        "os": os_name,
    }
    request["weeks"] = None if weeks is None else int(weeks)
    return request


def render_packs(packs: list[dict[str, Any]]) -> bytes:
    """Render packs as canonical JSON Lines bytes."""

    lines = [
        json.dumps(pack, sort_keys=True, separators=(",", ":")) + "\n" for pack in packs
    ]
    return "".join(lines).encode("utf-8")


def read_pack_files(paths: list[Path | str]) -> list[dict[str, Any]]:
    """Parse every non-blank line of every file as a JSON object."""

    parsed: list[dict[str, Any]] = []
    for raw_path in paths:
        path = Path(raw_path)
        text = path.read_text(encoding="utf-8")
        for lineno, line in enumerate(text.splitlines(), start=1):
            if not line.strip():
                continue
            try:
                value = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"{path}:{lineno}: invalid JSON: {exc}") from exc
            if not isinstance(value, dict):
                raise ValueError(f"{path}:{lineno}: expected a JSON object")
            parsed.append(dict(value))
    return parsed


__all__ = ["build_export_request", "read_pack_files", "render_packs"]
