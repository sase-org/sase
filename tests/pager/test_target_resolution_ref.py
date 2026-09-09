"""Tests for scanned pager spans becoming resolvable target refs."""

from __future__ import annotations

from sase.pager.document import PagerOrigin, PagerTargetSpan, target_resolution_ref
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
