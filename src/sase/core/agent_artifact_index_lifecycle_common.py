"""Shared types and configuration for artifact-index lifecycle maintenance."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sase.core.agent_cleanup_wire import AgentCleanupIdentityWire
from sase.core.agent_scan_wire import AgentArtifactScanOptionsWire
from sase.core.paths import sase_home as _sase_home

AgentIdentityLike = tuple[Any, str, str | None]
DismissedAgentsSignature = tuple[int, int] | None
DismissedBundleIndexSignature = tuple[int, int, int, int] | None

_LIFECYCLE_SCAN_OPTIONS = AgentArtifactScanOptionsWire(
    include_prompt_step_markers=True,
    include_raw_prompt_snippets=False,
)
_INDEX_ERRORS = (
    ImportError,
    AttributeError,
    OSError,
    RuntimeError,
    ValueError,
)


@dataclass(frozen=True)
class DismissedProjectionInputs:
    """Dismissed identities plus the source signatures used to build them."""

    identities: list[AgentCleanupIdentityWire]
    dismissed_agents_signature: DismissedAgentsSignature
    dismissed_bundle_index_signature: DismissedBundleIndexSignature
    skipped_bundle_rows: int = 0


def default_agent_artifact_projects_root(
    sase_home: Path | str | None = None,
) -> Path:
    """Return the default projects root used by the artifact index."""
    root = Path(sase_home).expanduser() if sase_home is not None else _sase_home()
    return root / "projects"
