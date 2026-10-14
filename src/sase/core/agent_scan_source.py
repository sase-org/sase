"""Lock-free source scans for agent artifacts.

These entry points call ``sase_core_rs`` directly through
:func:`sase.core.rust.require_rust_binding` without taking the artifact
index operation lock: they walk the filesystem (or parse one selector)
instead of touching the persistent SQLite index. The Rust extension is a
hard runtime dependency; a missing or stale wheel surfaces as
:class:`ImportError` / :class:`AttributeError`.
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import Any

from sase.core._agent_scan_shared import options_to_dict
from sase.core.agent_output_variable_selector_wire import OutputVariableSelectorWire
from sase.core.agent_output_variable_selector_wire import (
    output_variable_selector_from_dict,
)
from sase.core.agent_scan_wire import AgentArtifactScanOptionsWire
from sase.core.agent_scan_wire import AgentArtifactScanWire
from sase.core.agent_scan_wire import agent_scan_wire_from_dict
from sase.core.rust import require_rust_binding


def scan_agent_artifacts(
    projects_root: Path | str,
    options: AgentArtifactScanOptionsWire | None = None,
) -> AgentArtifactScanWire:
    """Return a snapshot of all agent artifact directories under *projects_root*.

    ``projects_root`` is required and is normally
    ``Path.home() / ".sase" / "projects"`` — passing it explicitly keeps the
    contract testable and lets future shells (server, mobile) supply a
    different root without Rust reading global config. The Rust binding
    releases the GIL during the filesystem walk.
    """
    opts = options or AgentArtifactScanOptionsWire()
    rust_scan = require_rust_binding("scan_agent_artifacts")
    payload: dict[str, Any] = rust_scan(str(projects_root), options_to_dict(opts))
    return agent_scan_wire_from_dict(payload)


def scan_agent_artifact_dirs(
    projects_root: Path | str,
    artifact_dirs: Sequence[Path | str],
    options: AgentArtifactScanOptionsWire | None = None,
) -> AgentArtifactScanWire:
    """Return a scanner-shaped snapshot for exact artifact directories."""
    opts = options or AgentArtifactScanOptionsWire()
    rust_scan = require_rust_binding("scan_agent_artifact_dirs")
    payload: dict[str, Any] = rust_scan(
        str(projects_root),
        [str(Path(path).expanduser()) for path in artifact_dirs],
        options_to_dict(opts),
    )
    return agent_scan_wire_from_dict(payload)


def parse_output_variable_selector(selector: str) -> OutputVariableSelectorWire:
    """Parse one ``sase var get`` selector through the Rust domain parser."""
    rust_parse = require_rust_binding("parse_output_variable_selector")
    payload: dict[str, Any] = rust_parse(selector)
    return output_variable_selector_from_dict(payload)


__all__ = [
    "parse_output_variable_selector",
    "scan_agent_artifact_dirs",
    "scan_agent_artifacts",
]
