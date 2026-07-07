"""Projects tab fixtures for Config Center PNG visual snapshots."""

from __future__ import annotations

import pytest

from sase.core.project_lifecycle_wire import ProjectRecordWire
from tests.ace.tui.visual._ace_png_snapshot_helpers import project_records


def _patch_project_records(
    monkeypatch: pytest.MonkeyPatch,
    records: list[ProjectRecordWire] | None = None,
) -> None:
    """Feed the always-mounted Projects pane deterministic lifecycle records.

    Overrides the ``conftest`` autouse stub (which returns an empty list to keep
    other Admin Center snapshots deterministic) so the Projects tab renders a
    stable spread of states, claims, aliases, and warnings.
    """
    resolved = project_records() if records is None else records
    monkeypatch.setattr(
        "sase.ace.tui.modals.projects_pane.list_project_records",
        lambda *_a, **_kw: list(resolved),
    )
