"""Descriptor and lookup integration coverage for artifact contracts."""

from __future__ import annotations

from pathlib import Path

import pytest

from sase.ace.tui._artifact_tab_descriptors import (
    assign_artifacts_digit_shortcuts,
    fixed_descriptor,
    provider_descriptors,
)
from sase.ace.tui._artifact_tab_model import (
    PaneCapability,
    ProjectProviderRecord,
    ProviderDiscoveryIssue,
)
from sase.ace.tui.artifact_tabs import (
    artifacts_pane_contract,
    configured_artifacts_pane_ids,
    descriptor_for_artifacts_pane_id,
    descriptor_for_artifacts_subtab,
    reset_artifacts_subtabs_cache,
)
from sase.sidecar_ref_config import SidecarRefPolicy

from .contract_compiler_support import document_spec


def test_invalid_suppression_marks_provider_descriptor_degraded() -> None:
    spec = document_spec(capabilities={"enable": True})
    descriptors = provider_descriptors(
        (
            ProjectProviderRecord(
                project="proj",
                display_name="Proj",
                workspace_dir="/tmp/proj",
                role="notes",
                root=Path("/tmp/proj"),
                policy=SidecarRefPolicy(
                    role="notes",
                    ref_kind="notes",
                    is_document=True,
                    spec=spec,
                ),
            ),
        )
    )
    assert len(descriptors) == 1
    assert descriptors[0].is_degraded
    assert descriptors[0].error_code == "invalid_ref_capabilities"
    assert descriptors[0].contract is not None
    assert descriptors[0].contract.has(PaneCapability.REFRESH)


def test_degraded_descriptor_satisfies_every_conformance_check() -> None:
    """A degraded provider stays named/navigable and renders the shared shell.

    Runs the full conformance harness (including the shell-render check)
    against a genuinely degraded descriptor, not just the healthy built-ins
    and synthetic provider covered elsewhere.
    """
    from .harness import PANE_CONFORMANCE_CHECKS

    spec = document_spec(capabilities={"enable": True})
    descriptors = provider_descriptors(
        (
            ProjectProviderRecord(
                project="proj",
                display_name="Proj",
                workspace_dir="/tmp/proj",
                role="notes",
                root=Path("/tmp/proj"),
                policy=SidecarRefPolicy(
                    role="notes",
                    ref_kind="notes",
                    is_document=True,
                    spec=spec,
                ),
            ),
        )
    )
    assert descriptors[0].is_degraded
    for _name, check in PANE_CONFORMANCE_CHECKS:
        check(descriptors[0])


def test_digit_assignment_synchronizes_contract() -> None:
    descriptors = assign_artifacts_digit_shortcuts(
        (
            fixed_descriptor("stitches"),
            fixed_descriptor("patches"),
            fixed_descriptor("beads"),
            fixed_descriptor("files"),
        )
    )
    for index, descriptor in enumerate(descriptors):
        assert descriptor.contract is not None
        assert descriptor.digit_shortcut == str(index + 1)
        assert descriptor.contract.digit == descriptor.digit_shortcut
        assert descriptor.contract.order == index
        assert descriptor.contract.label == descriptor.label


def test_exact_lookup_does_not_normalize_unknown_ids(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reset_artifacts_subtabs_cache()
    monkeypatch.setattr(
        "sase.ace.tui.artifact_tabs.resolve_artifacts_subtabs",
        lambda: assign_artifacts_digit_shortcuts(
            (
                fixed_descriptor("stitches"),
                fixed_descriptor("patches"),
                fixed_descriptor("beads"),
                fixed_descriptor("files"),
            )
        ),
    )
    assert descriptor_for_artifacts_pane_id("missing") is None
    assert artifacts_pane_contract("missing") is None
    assert descriptor_for_artifacts_subtab("missing") is not None
    assert descriptor_for_artifacts_subtab("missing").id == "stitches"
    assert configured_artifacts_pane_ids() == (
        "stitches",
        "patches",
        "beads",
        "files",
    )


def test_degraded_discovery_keeps_safe_contract() -> None:
    descriptors = provider_descriptors(
        (),
        (
            ProviderDiscoveryIssue(
                message="artifact ref provider 'research-docs' is not installed",
                code="missing_ref_provider",
                kind="research",
            ),
        ),
    )
    descriptor = descriptors[0]
    assert descriptor.is_degraded
    assert descriptor.contract is not None
    assert descriptor.contract.has(PaneCapability.REFRESH)
    assert not descriptor.contract.has(PaneCapability.FILTER_SESSION)
    assert not descriptor.contract.has(PaneCapability.MUTATION)
