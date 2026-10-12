"""Inventory coverage for the Artifacts Agent pane retirement sunset flag.

With ``artifacts_agent_pane_retired`` on (the default), the Agent pane is
hidden and Stitch takes digit 1; with it off, the pane sits first on digit 1
with Files still last on the highest digit. The parametrized sweep in
``test_conformance.py`` covers the retired default via
``resolve_artifacts_subtabs()``; this module pins the ordering guarantee in
both states.
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
    normalize_artifacts_subtab,
    resolve_artifacts_subtabs,
)
from sase.feature_flags import override_flags


def _fixed_ids(descriptors: Iterable[ArtifactsTabDescriptor]) -> tuple[str, ...]:
    return tuple(
        descriptor.id
        for descriptor in descriptors
        if descriptor.id in FIXED_ARTIFACTS_SUBTAB_ORDER
    )


def test_retired_pane_hides_agents_and_renumbers_stitch_to_1() -> None:
    artifact_tabs.reset_artifacts_subtabs_cache()
    try:
        with override_flags(artifacts_agent_pane_retired=True):
            descriptors = resolve_artifacts_subtabs()
    finally:
        artifact_tabs.reset_artifacts_subtabs_cache()
    ids = tuple(descriptor.id for descriptor in descriptors)
    assert "agents" not in ids
    assert ids[0] == "stitches"
    assert ids[-1] == "files"
    stitches = next(d for d in descriptors if d.id == "stitches")
    files = next(d for d in descriptors if d.id == "files")
    assert stitches.digit_shortcut == "1"
    assert files.digit_shortcut == str(len(descriptors))
    with override_flags(artifacts_agent_pane_retired=True):
        assert normalize_artifacts_subtab("agents") == "stitches"


def test_flag_off_restores_agents_pane_first_on_digit_1() -> None:
    artifact_tabs.reset_artifacts_subtabs_cache()
    try:
        with override_flags(artifacts_agent_pane_retired=False):
            descriptors = resolve_artifacts_subtabs()
    finally:
        artifact_tabs.reset_artifacts_subtabs_cache()
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
        # Fast startup always mounts the flag-off shape, so compare against
        # the flag-off production order.
        with override_flags(artifacts_agent_pane_retired=False):
            production_fixed_ids = _fixed_ids(artifact_tabs.resolve_artifacts_subtabs())
    finally:
        artifact_tabs.reset_artifacts_subtabs_cache()

    assert _fixed_ids(_fast_artifacts_subtabs()) == production_fixed_ids
