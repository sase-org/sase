"""Inventory coverage for the two Artifacts fixed-pane feature flags."""

from __future__ import annotations

from collections.abc import Iterable
from itertools import product
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
        with override_flags(
            artifacts_agent_pane_retired=True,
            artifacts_files_pane=True,
        ):
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
        with override_flags(
            artifacts_agent_pane_retired=False,
            artifacts_files_pane=True,
        ):
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
    with override_flags(artifacts_agent_pane_retired=False):
        assert normalize_artifacts_subtab("agents") == "agents"


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
        # Fast startup follows production in all four combinations.
        for retired, files_enabled in product((False, True), repeat=2):
            artifact_tabs.reset_artifacts_subtabs_cache()
            with override_flags(
                artifacts_agent_pane_retired=retired,
                artifacts_files_pane=files_enabled,
            ):
                production_fixed_ids = _fixed_ids(
                    artifact_tabs.resolve_artifacts_subtabs()
                )
                assert _fixed_ids(_fast_artifacts_subtabs()) == production_fixed_ids
    finally:
        artifact_tabs.reset_artifacts_subtabs_cache()
