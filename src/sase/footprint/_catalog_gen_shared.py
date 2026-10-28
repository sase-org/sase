"""Shared types and helpers for Footprint catalog generation."""

from __future__ import annotations

import importlib.resources
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml  # type: ignore[import-untyped]

ENTRY_KEYS = ("id", "ns", "area", "kind", "label", "parent", "src")


@dataclass
class Entry:
    id: str
    ns: str
    area: str
    kind: str
    label: str
    parent: str | None = None
    src: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {key: getattr(self, key) for key in ENTRY_KEYS}


def package_resource(*parts: str) -> Path:
    """Return a path under the installed ``sase`` package."""
    return Path(str(importlib.resources.files("sase").joinpath("/".join(parts))))


def load_bundled_config() -> dict[str, Any]:
    """Load the bundled ``default_config.yml``."""
    return yaml.safe_load(package_resource("default_config.yml").read_text())


def humanize(name: str) -> str:
    return name.replace("_", " ").strip().capitalize() or name


def first_line(text: str, limit: int = 160) -> str:
    line = (text or "").strip().splitlines()[0] if (text or "").strip() else ""
    return line[:limit] if len(line) <= limit else line[:limit].rstrip() + "…"
