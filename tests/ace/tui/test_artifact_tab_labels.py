"""Regression coverage for Artifacts collection labels and item nouns."""

from __future__ import annotations

from pathlib import Path

from sase.ace.tui._artifact_tab_descriptors import (
    _provider_label,
    fixed_descriptor,
    provider_descriptors,
)
from sase.ace.tui._artifact_tab_model import (
    ARTIFACTS_ITEM_NOUNS,
    ARTIFACTS_LABELS,
    ProjectProviderRecord,
    provider_item_noun,
)
from sase.ace.tui.artifact_tabs import FIXED_ARTIFACTS_SUBTAB_ORDER
from sase.ace.tui.commands.catalog import _iter_artifacts_subtab_commands
from sase.artifact_providers import builtin_plan_ref_provider_spec
from sase.artifact_providers._validation import validate_ref_provider_spec
from sase.sidecar_ref_config import SidecarRefPolicy
from tests.ace.tui.artifacts_contract.contract_compiler_support import document_spec

_EXPECTED_FIXED_LABELS = {
    "agents": "Agent",
    "stitches": "Commits",
    "patches": "Patches",
    "beads": "Beads",
    "files": "Files",
}
_EXPECTED_FIXED_ITEM_NOUNS = {
    "agents": "Agent",
    "stitches": "Commit",
    "patches": "Patch",
    "beads": "Bead",
    "files": "File",
}


def test_fixed_artifact_collection_labels_and_item_nouns() -> None:
    labels = {
        subtab: fixed_descriptor(subtab).label
        for subtab in FIXED_ARTIFACTS_SUBTAB_ORDER
    }
    item_nouns = {
        subtab: fixed_descriptor(subtab).item_noun
        for subtab in FIXED_ARTIFACTS_SUBTAB_ORDER
    }

    assert labels == _EXPECTED_FIXED_LABELS
    assert item_nouns == _EXPECTED_FIXED_ITEM_NOUNS
    assert ARTIFACTS_LABELS == {
        **_EXPECTED_FIXED_LABELS,
        "ref:plan": "Plans",
    }
    assert ARTIFACTS_ITEM_NOUNS == {
        **_EXPECTED_FIXED_ITEM_NOUNS,
        "ref:plan": "Plan",
    }


def test_provider_label_derives_singular_title_case() -> None:
    assert _provider_label("plan", {}) == "Plan"


def test_provider_label_empty_kind_falls_back_to_document() -> None:
    assert _provider_label("", {}) == "Document"
    assert provider_item_noun("") == "Document"


def test_provider_label_configured_spec_wins_verbatim() -> None:
    assert _provider_label("plan", {"label": "Plans"}) == "Plans"


def test_builtin_plan_descriptor_uses_plural_label_and_singular_item_noun() -> None:
    spec = builtin_plan_ref_provider_spec()
    record = ProjectProviderRecord(
        project="proj",
        display_name="Proj",
        workspace_dir="/tmp/proj",
        role="plans",
        root=Path("/tmp/proj"),
        policy=SidecarRefPolicy(
            role="plans",
            ref_kind="plan",
            is_document=True,
            spec=spec,
        ),
    )

    descriptor = provider_descriptors((record,))[0]

    assert descriptor.label == "Plans"
    assert descriptor.item_noun == "Plan"
    assert ARTIFACTS_LABELS["ref:plan"] == descriptor.label
    assert descriptor.contract is not None
    assert descriptor.contract.empty_state.title == "No plans"
    assert descriptor.contract.explanation_payload()["item_noun"] == "Plan"


def test_builtin_plan_pane_label_does_not_change_rust_provider_digest() -> None:
    spec = builtin_plan_ref_provider_spec()
    ref = spec["ref"]
    assert isinstance(ref, dict)
    pane = ref.pop("pane")

    try:
        with_pane_digest = validate_ref_provider_spec(
            spec | {"ref": ref | {"pane": pane}}
        )
        without_pane_digest = validate_ref_provider_spec(spec)
    finally:
        ref["pane"] = pane

    assert with_pane_digest == without_pane_digest


def test_unlabeled_research_provider_keeps_collection_and_item_nouns_distinct() -> None:
    spec = document_spec(kind="research")
    record = ProjectProviderRecord(
        project="proj",
        display_name="Proj",
        workspace_dir="/tmp/proj",
        role="research",
        root=Path("/tmp/proj"),
        policy=SidecarRefPolicy(
            role="research",
            ref_kind="research",
            is_document=True,
            spec=spec,
        ),
    )

    descriptor = provider_descriptors((record,))[0]

    assert descriptor.label == "Research"
    assert descriptor.item_noun == "Research"
    assert descriptor.contract is not None
    assert descriptor.contract.empty_state.title == "No research"
    assert descriptor.contract.empty_state.body == (
        "No research documents match the current project scope and filters."
    )
    assert "researchs" not in repr(descriptor.contract.explanation_payload())


def test_artifact_palette_aliases_include_collection_and_item_names() -> None:
    commands = {command.id: command for command in _iter_artifacts_subtab_commands()}

    stitches = commands["artifacts.stitches"]
    patches = commands["artifacts.patches"]
    beads = commands["artifacts.beads"]
    files = commands["artifacts.files"]

    assert "artifact Commits" in stitches.aliases
    assert "artifact Commit" in stitches.aliases
    assert "stitch" in stitches.aliases and "commits" in stitches.aliases
    assert "artifact Patches" in patches.aliases
    assert "artifact Patch" in patches.aliases
    assert {"patch", "prs"}.issubset(patches.aliases)
    assert {"artifact Beads", "artifact Bead", "bugs", "issues"}.issubset(beads.aliases)
    assert {"artifact Files", "artifact File", "file"}.issubset(files.aliases)
