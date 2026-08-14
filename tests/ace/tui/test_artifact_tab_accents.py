"""Deterministic Artifacts provider accents."""

from __future__ import annotations

from pathlib import Path

from sase.ace.tui._artifact_tab_descriptors import (
    _provider_accent_for_kind,
    provider_descriptors,
)
from sase.ace.tui._artifact_tab_model import ProjectProviderRecord
from sase.ace.tui.artifact_tabs import ARTIFACTS_ACCENTS
from sase.sidecar_ref_config import SidecarRefPolicy


def _record(kind: str) -> ProjectProviderRecord:
    return ProjectProviderRecord(
        project="proj",
        display_name="Proj",
        workspace_dir="/tmp/proj",
        role=kind,
        root=Path("/tmp/proj"),
        policy=SidecarRefPolicy(role=kind, ref_kind=kind, is_document=True),
    )


def test_plan_keeps_pinned_builtin_accent() -> None:
    assert _provider_accent_for_kind("plan") == ARTIFACTS_ACCENTS["ref:plan"]
    assert _provider_accent_for_kind("plan") == "#AF87FF"


def test_provider_accent_is_stable_and_independent_of_other_kinds() -> None:
    research_alone = _provider_accent_for_kind("research")
    research_with_design = _provider_accent_for_kind("research")
    assert research_alone == research_with_design
    assert _provider_accent_for_kind("research") == _provider_accent_for_kind(
        "research"
    )
    assert _provider_accent_for_kind("design") != ""


def test_provider_accent_never_uses_a_builtin_colour() -> None:
    reserved = frozenset(ARTIFACTS_ACCENTS.values())
    for kind in ("research", "design", "notes", "zz_alpha", "zz_beta"):
        assert _provider_accent_for_kind(kind) not in reserved


def test_provider_descriptors_do_not_write_artifacts_accents() -> None:
    before = dict(ARTIFACTS_ACCENTS)
    descriptors = provider_descriptors(
        [_record("zz_alpha_accent"), _record("zz_beta_accent")]
    )
    assert dict(ARTIFACTS_ACCENTS) == before
    assert "ref:zz_alpha_accent" not in ARTIFACTS_ACCENTS
    assert {descriptor.id: descriptor.accent for descriptor in descriptors} == {
        "ref:zz_alpha_accent": _provider_accent_for_kind("zz_alpha_accent"),
        "ref:zz_beta_accent": _provider_accent_for_kind("zz_beta_accent"),
    }
