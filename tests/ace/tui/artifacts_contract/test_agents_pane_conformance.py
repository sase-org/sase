"""Inventory coverage for the Artifacts Agent pane.

The pane is unconditional, so the parametrized sweep in ``test_conformance.py``
already covers it via the default ``resolve_artifacts_subtabs()`` collection.
This module pins the inventory-ordering guarantee that sweep does not check:
the pane sits first, on digit 1, with Files still last on the highest digit.
"""

from __future__ import annotations

from collections.abc import Iterable
from types import SimpleNamespace

import pytest

from sase.ace.testing._startup import _fast_artifacts_subtabs
from sase.ace.tui import artifact_tabs
from sase.ace.tui._artifact_tab_model import FIXED_ARTIFACTS_SUBTAB_ORDER
from sase.ace.tui.artifact_tabs import (
    ArtifactsTabDescriptor,
    resolve_artifacts_subtabs,
)


def _fixed_ids(descriptors: Iterable[ArtifactsTabDescriptor]) -> tuple[str, ...]:
    return tuple(
        descriptor.id
        for descriptor in descriptors
        if descriptor.id in FIXED_ARTIFACTS_SUBTAB_ORDER
    )


def test_agents_pane_inserted_first_with_files_last() -> None:
    descriptors = resolve_artifacts_subtabs()
    ids = tuple(descriptor.id for descriptor in descriptors)
    assert "agents" in ids
    assert ids[0] == "agents"
    assert ids[-1] == "files"
    agents = next(d for d in descriptors if d.id == "agents")
    files = next(d for d in descriptors if d.id == "files")
    assert agents.digit_shortcut == "1"
    assert files.digit_shortcut == str(len(descriptors))
    assert not agents.is_degraded


def test_fast_startup_fixed_pane_order_matches_production(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def empty_provider_records(*, project: str | None = None) -> SimpleNamespace:
        del project
        return SimpleNamespace(records=(), issues=())

    artifact_tabs.reset_artifacts_subtabs_cache()
    monkeypatch.setattr(
        artifact_tabs,
        "load_project_provider_records",
        empty_provider_records,
    )
    try:
        production_fixed_ids = _fixed_ids(artifact_tabs.resolve_artifacts_subtabs())
    finally:
        artifact_tabs.reset_artifacts_subtabs_cache()

    assert _fixed_ids(_fast_artifacts_subtabs()) == production_fixed_ids
