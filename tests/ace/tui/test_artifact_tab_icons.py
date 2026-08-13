"""Unit coverage for Artifacts tab icon resolution."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from rich.cells import cell_len

from sase.ace.tui import artifact_tabs
from sase.ace.tui.artifact_tabs import (
    ARTIFACTS_ICONS,
    DEFAULT_DOCUMENT_TAB_ICON,
    _ProjectProviderRecord,
    _fixed_descriptor,
    _provider_descriptors,
    _sanitize_tab_icon,
)
from sase.artifact_providers import builtin_plan_ref_provider_spec
from sase.sidecar_ref_config import SidecarRefPolicy


def test_fixed_artifact_pane_descriptors_carry_builtin_icons() -> None:
    assert {
        subtab: _fixed_descriptor(subtab).icon for subtab in ARTIFACTS_ICONS
    } == ARTIFACTS_ICONS


def test_provider_descriptor_takes_icon_from_spec() -> None:
    descriptors = _provider_descriptors([_record("research", icon="∴")])

    assert len(descriptors) == 1
    assert descriptors[0].id == "ref:research"
    assert descriptors[0].icon == "∴"


@pytest.mark.parametrize(
    "ref_updates",
    [
        {},
        {"icon": "ab"},
    ],
)
def test_provider_descriptor_falls_back_to_generic_icon(
    ref_updates: dict[str, Any],
) -> None:
    descriptors = _provider_descriptors([_record("notes", **ref_updates)])

    assert len(descriptors) == 1
    assert descriptors[0].icon == DEFAULT_DOCUMENT_TAB_ICON


@pytest.mark.parametrize("raw", ["ab", "\n"])
def test_sanitize_tab_icon_rejects_malformed_input(raw: str) -> None:
    assert _sanitize_tab_icon(raw) == ""


def test_sanitize_tab_icon_rejects_overwide_input(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(artifact_tabs, "cell_len", lambda _icon: 3)

    assert _sanitize_tab_icon("✎") == ""


def test_repo_shipped_artifact_tab_icons_are_single_cell() -> None:
    icons = (
        *ARTIFACTS_ICONS.values(),
        DEFAULT_DOCUMENT_TAB_ICON,
        builtin_plan_ref_provider_spec()["ref"]["icon"],
    )

    assert {icon: cell_len(icon) for icon in icons} == dict.fromkeys(icons, 1)


def _record(kind: str, **ref_updates: Any) -> _ProjectProviderRecord:
    spec = {
        "schema_version": 1,
        "provider": kind,
        "ref": {
            "kind": kind,
            "expansion_format": "{kind}:{argument}",
            "properties": {},
            "detail": {},
            "identity": {},
            "inventory": {},
            "publication": {},
            **ref_updates,
        },
    }
    return _ProjectProviderRecord(
        project="proj",
        display_name="Proj",
        workspace_dir="/tmp/proj",
        role=kind,
        root=Path("/tmp/proj"),
        policy=SidecarRefPolicy(
            role=kind,
            ref_kind=kind,
            is_document=True,
            spec=spec,
        ),
    )
