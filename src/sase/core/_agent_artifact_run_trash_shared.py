"""Shared helpers for the ACE-run trash split.

The names here are public so the sibling ``agent_artifact_run_trash_*``
modules can import them without touching a ``_``-prefixed symbol across
files. Each helper keeps the behavior the former monolithic
:mod:`sase.core.agent_artifact_run_trash` module used.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

from sase.core.agent_artifact_run_trash_models import (
    AGENT_ARTIFACT_RUN_TRASH_WIRE_SCHEMA_VERSION,
)
from sase.core.paths import sase_home
from sase.core.rust import require_rust_binding


def run_trash_root() -> Path:
    """Return the ACE-run trash root, outside every scanned projects tree."""

    return sase_home() / "trash" / "ace-run"


def require_run_trash_wire_schema() -> None:
    """Refuse when the Rust trash owner speaks a different wire schema."""

    binding = require_rust_binding("agent_artifact_run_trash_wire_schema_version")
    actual = int(binding())
    if actual != AGENT_ARTIFACT_RUN_TRASH_WIRE_SCHEMA_VERSION:
        raise RuntimeError(
            "sase_core_rs agent artifact run trash wire schema "
            f"{actual} is incompatible with Python schema "
            f"{AGENT_ARTIFACT_RUN_TRASH_WIRE_SCHEMA_VERSION}"
        )


def call_run_trash_binding(name: str, request: Mapping[str, Any] | None = None) -> Any:
    """Call one ACE-run trash binding after checking the wire schema."""

    require_run_trash_wire_schema()
    binding = require_rust_binding(name)
    payload = binding(dict(request)) if request is not None else binding()
    assert isinstance(payload, dict)
    return payload


def normalized_dir(value: Path | str) -> str:
    """Canonicalize *value* the way trash requests key run directories."""

    return str(Path(value).expanduser().resolve(strict=False))


__all__ = [
    "call_run_trash_binding",
    "normalized_dir",
    "require_run_trash_wire_schema",
    "run_trash_root",
]
