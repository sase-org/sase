"""Bundle-path resolution behavior of the saved-group record builder.

These lock the perf contract from
``sdd/tales/202606/recent_restore_perf_fix.md``: the optimistic UI-thread build
must not probe the filesystem for dismissed bundles, while off-UI-thread callers
keep the disk-resolving default.
"""

from __future__ import annotations

from unittest.mock import patch

from sase.ace.tui.actions.agents._recent_dismissal_groups import (
    build_recent_dismissed_agent_group,
)
from sase.ace.tui.actions.agents._saved_group_records import build_saved_agent_group

from tests.ace.tui._agent_marking_helpers import _make_agent

_PROBE = "sase.ace.dismissed_agents.dismissed_bundle_path_for_agent"


def test_resolve_bundle_paths_false_skips_disk_probe() -> None:
    """The optimistic UI-thread build must not touch the filesystem."""
    agent = _make_agent(raw_suffix="20240101120000")

    with patch(_PROBE) as mock_probe:
        group = build_saved_agent_group([agent], resolve_bundle_paths=False)

    mock_probe.assert_not_called()
    assert group.agent_refs[0].bundle_path is None


def test_resolve_bundle_paths_false_honors_in_memory_path() -> None:
    """A revived-then-re-dismissed agent keeps its cached bundle path."""
    agent = _make_agent(
        raw_suffix="20240101120000",
        _dismissed_bundle_path="/bundles/202401/agent.json",
    )

    with patch(_PROBE) as mock_probe:
        group = build_saved_agent_group([agent], resolve_bundle_paths=False)

    mock_probe.assert_not_called()
    assert group.agent_refs[0].bundle_path == "/bundles/202401/agent.json"


def test_recent_dismissed_group_build_skips_disk_probe() -> None:
    """The recent-dismissal builder feeds the hot dismiss/kill paths I/O-free."""
    agent = _make_agent(raw_suffix="20240101120000")

    with patch(_PROBE) as mock_probe:
        group = build_recent_dismissed_agent_group([agent])

    mock_probe.assert_not_called()
    assert group is not None
    assert group.source == "recent_dismissal"
    assert group.agent_refs[0].bundle_path is None


def test_resolve_bundle_paths_default_uses_helper() -> None:
    """Default (True) preserves disk resolution for off-UI-thread callers."""
    agent = _make_agent(raw_suffix="20240101120000")

    with patch(_PROBE, return_value="/bundles/202401/resolved.json") as mock_probe:
        group = build_saved_agent_group([agent])

    mock_probe.assert_called_once()
    assert group.agent_refs[0].bundle_path == "/bundles/202401/resolved.json"
