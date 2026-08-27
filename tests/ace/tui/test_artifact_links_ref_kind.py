"""Tests for the ref/target conversion halves shared with LinkIndex.

``parse_link_ref`` and ``target_for_ref_kind`` were extracted out of
``_target_for_ref`` (bead:sase-ug.5) so an app-level index can synthesize a
target without a pane's ``known_targets`` scope. This file locks in that
this was a pure extraction: same kind/payload split, same synthesis.
"""

from __future__ import annotations

from sase.ace.tui.relations.artifact_links import parse_link_ref, target_for_ref_kind
from sase.core.artifact_entry_target import ArtifactEntryTarget


def test_parse_link_ref_splits_kind_and_payload() -> None:
    assert parse_link_ref("bead:sase-1") == ("bead", "sase-1")


def test_parse_link_ref_aliases_commit_to_stitch() -> None:
    assert parse_link_ref("commit:sase@abc123") == ("stitch", "sase@abc123")


def test_parse_link_ref_strips_leading_at_and_trailing_fragment() -> None:
    assert parse_link_ref("@plan:202608/a.md#why") == ("plan", "202608/a.md")


def test_parse_link_ref_rejects_a_ref_with_no_kind() -> None:
    assert parse_link_ref("not-a-ref") is None
    assert parse_link_ref("kind:") is None


def test_target_for_ref_kind_stitch_requires_a_repo_and_sha() -> None:
    assert target_for_ref_kind(
        "stitch", "sase@0123456789abcdef", project_hint=None
    ) == ArtifactEntryTarget("stitches", ("sase", "0123456789abcdef"))
    assert target_for_ref_kind("stitch", "no-at-sign", project_hint=None) is None


def test_target_for_ref_kind_falls_back_to_the_document_provider_shape() -> None:
    assert target_for_ref_kind(
        "research", "202608/report.md", project_hint="alpha"
    ) == ArtifactEntryTarget("ref:research", ("alpha", "archive", "202608/report.md"))


def test_target_for_ref_kind_has_no_target_for_bug_chat_or_chop() -> None:
    for kind in ("bug", "chat", "chop"):
        assert target_for_ref_kind(kind, "x", project_hint=None) is None
