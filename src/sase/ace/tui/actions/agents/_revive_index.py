"""Artifact-index lifecycle calls used by agent revival.

The public ``_revive`` module historically exported these names directly, and
tests patch those exports. These thin wrappers keep that patch point working
after the implementation moved into smaller modules.
"""

from __future__ import annotations

import sys
from typing import Any

from sase.core.agent_artifact_index_lifecycle import (
    sync_dismissed_agent_artifact_index as _core_sync_dismissed_agent_artifact_index,
)
from sase.core.agent_artifact_index_lifecycle import (
    upsert_agent_artifact_index_artifacts as _core_upsert_agent_artifact_index_artifacts,
)

_REVIVE_MODULE = "sase.ace.tui.actions.agents._revive"


def _patched_revive_export(name: str, original: object) -> Any | None:
    module = sys.modules.get(_REVIVE_MODULE)
    if module is None:
        return None
    target = getattr(module, name, None)
    if target is None or target is original:
        return None
    return target


def sync_dismissed_agent_artifact_index(*args: Any, **kwargs: Any) -> Any:
    """Call the dismissed-agent index sync, honoring the legacy patch point."""
    patched = _patched_revive_export(
        "sync_dismissed_agent_artifact_index",
        sync_dismissed_agent_artifact_index,
    )
    if patched is not None:
        return patched(*args, **kwargs)
    return _core_sync_dismissed_agent_artifact_index(*args, **kwargs)


def upsert_agent_artifact_index_artifacts(*args: Any, **kwargs: Any) -> Any:
    """Call the artifact-index upsert, honoring the legacy patch point."""
    patched = _patched_revive_export(
        "upsert_agent_artifact_index_artifacts",
        upsert_agent_artifact_index_artifacts,
    )
    if patched is not None:
        return patched(*args, **kwargs)
    return _core_upsert_agent_artifact_index_artifacts(*args, **kwargs)
