"""Tests for scanned pager spans becoming resolvable target refs."""

from __future__ import annotations

from sase.artifact_ref_models import ArtifactRefDocumentTarget, ArtifactRefSpan
from sase.pager.document import (
    PagerOrigin,
    PagerTargetSpan,
    target_action_destination,
    target_resolution_ref,
)
from sase.pager.link_scan import LinkSpanKind

from ._resolve_helpers import _span


def test_target_resolution_ref_prefixes_bare_bead_tokens_in_bead_origin() -> None:
    span = _span(LinkSpanKind.BARE_TOKEN, "sase-uk.5")
    assert target_resolution_ref(span, PagerOrigin.BEAD) == "bead:sase-uk.5"


def test_target_resolution_ref_ignores_bare_tokens_outside_bead_origin() -> None:
    span = _span(LinkSpanKind.BARE_TOKEN, "sase-uk.5")
    assert target_resolution_ref(span, PagerOrigin.FILE) is None


def test_target_resolution_ref_prefixes_bare_shas_in_diff_origin() -> None:
    span = _span(LinkSpanKind.BARE_TOKEN, "deadbee1")
    assert target_resolution_ref(span, PagerOrigin.DIFF) == "commit:deadbee1"


def test_target_resolution_ref_never_resolves_urls() -> None:
    span = _span(LinkSpanKind.URL, "https://example.test")
    assert target_resolution_ref(span, PagerOrigin.FILE) is None


def test_target_resolution_ref_passes_through_artifact_refs_and_paths() -> None:
    ref_span = _span(LinkSpanKind.ARTIFACT_REF, "bead:sase-uk.5")
    path_span = _span(LinkSpanKind.FILE_PATH, "src/sase/pager/app.py")
    assert target_resolution_ref(ref_span, PagerOrigin.FILE) == "bead:sase-uk.5"
    assert target_resolution_ref(path_span, PagerOrigin.FILE) == "src/sase/pager/app.py"


def test_target_resolution_ref_uses_semantic_scanned_target() -> None:
    span = PagerTargetSpan(
        kind=LinkSpanKind.ARTIFACT_REF.value,
        target="plan:a b.md",
        start=0,
        end=len('@plan:"a b.md"'),
        text='@plan:"a b.md"',
        source="scanned",
    )

    assert target_resolution_ref(span, PagerOrigin.FILE) == "plan:a b.md"


def test_xprompt_skill_target_uses_hash_reference_for_resolution_and_copy() -> None:
    semantic = ArtifactRefDocumentTarget(
        schema_version=2,
        target_kind="xprompt_skill",
        text="[plan](#skill/sase_plan)",
        target="skill/sase_plan",
        well_formed=True,
        source_span=ArtifactRefSpan(0, 24),
        candidate_span=ArtifactRefSpan(0, 24),
        target_span=ArtifactRefSpan(7, 23),
        label_span=ArtifactRefSpan(1, 5),
        destination_span=ArtifactRefSpan(7, 23),
        markdown_destination="#skill/sase_plan",
    )
    span = PagerTargetSpan(
        kind=LinkSpanKind.XPROMPT_SKILL.value,
        target="skill/sase_plan",
        start=0,
        end=24,
        text="[plan](#skill/sase_plan)",
        source="scanned",
        semantic_target=semantic,
    )

    assert target_resolution_ref(span, PagerOrigin.FILE) == "#skill/sase_plan"
    assert target_action_destination(span, PagerOrigin.FILE) == "#skill/sase_plan"


def test_explicit_at_file_path_keeps_at_marker_as_action_destination() -> None:
    semantic = ArtifactRefDocumentTarget(
        schema_version=2,
        target_kind="file_path",
        text="@/sase_plan",
        target="/sase_plan",
        well_formed=True,
        source_span=ArtifactRefSpan(0, 11),
        candidate_span=ArtifactRefSpan(0, 11),
        target_span=ArtifactRefSpan(1, 11),
        label_span=None,
        destination_span=None,
    )
    span = PagerTargetSpan(
        kind=LinkSpanKind.FILE_PATH.value,
        target="/sase_plan",
        start=0,
        end=11,
        text="@/sase_plan",
        source="scanned",
        semantic_target=semantic,
    )

    assert target_action_destination(span, PagerOrigin.FILE) == "@/sase_plan"
