"""Path display helpers for the mobile notification bridge."""

from __future__ import annotations

from pathlib import Path


def normalize_home_path(value: str) -> str:
    expanded = str(Path(value).expanduser())
    home = str(Path.home())
    if expanded == home:
        return "~"
    if expanded.startswith(f"{home}/"):
        return f"~/{expanded[len(home) + 1 :]}"
    return value
