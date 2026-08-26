"""Regression coverage locking the singular Artifacts sub-tab labels."""

from __future__ import annotations

from sase.ace.tui._artifact_tab_descriptors import _provider_label, fixed_descriptor
from sase.ace.tui.artifact_tabs import FIXED_ARTIFACTS_SUBTAB_ORDER

_EXPECTED_FIXED_LABELS = {
    "agents": "Agent",
    "stitches": "Stitch",
    "patches": "Patch",
    "beads": "Bead",
    "files": "File",
}


def test_fixed_artifact_labels_are_singular() -> None:
    labels = {
        subtab: fixed_descriptor(subtab).label
        for subtab in FIXED_ARTIFACTS_SUBTAB_ORDER
    }

    assert labels == _EXPECTED_FIXED_LABELS
    assert all(not label.casefold().endswith("s") for label in labels.values())


def test_provider_label_derives_singular_title_case() -> None:
    assert _provider_label("plan", {}) == "Plan"


def test_provider_label_empty_kind_falls_back_to_document() -> None:
    assert _provider_label("", {}) == "Document"


def test_provider_label_configured_spec_wins_verbatim() -> None:
    assert _provider_label("plan", {"label": "Plans"}) == "Plans"
