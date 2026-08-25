"""Inventory coverage for the Artifacts Agent pane.

The pane is unconditional, so the parametrized sweep in ``test_conformance.py``
already covers it via the default ``resolve_artifacts_subtabs()`` collection.
This module pins the inventory-ordering guarantee that sweep does not check:
the pane sits immediately before Files, on the correct digit shortcuts.
"""

from __future__ import annotations

from sase.ace.tui.artifact_tabs import resolve_artifacts_subtabs


def test_agents_pane_inserted_immediately_before_files() -> None:
    descriptors = resolve_artifacts_subtabs()
    ids = tuple(descriptor.id for descriptor in descriptors)
    assert "agents" in ids
    assert ids[-2:] == ("agents", "files")
    agents = next(d for d in descriptors if d.id == "agents")
    files = next(d for d in descriptors if d.id == "files")
    assert agents.digit_shortcut == str(len(descriptors) - 1)
    assert files.digit_shortcut == str(len(descriptors))
    assert not agents.is_degraded
