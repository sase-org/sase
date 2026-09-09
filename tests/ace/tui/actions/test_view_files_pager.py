"""Tests for view-file pager document construction."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from sase.ace.tui.actions.hints._files import _COMMIT_TARGET_KIND, build_pager_document
from sase.pager.document import PagerOrigin, section_target_spans
from sase.pager.link_context import LinkAnchor, LinkResolutionContext
from sase.pager.link_scan import LinkSpanKind

from ._view_files_helpers import _commit_spec


def test_build_pager_document_files_only_matches_document_from_paths(
    tmp_path: Path,
) -> None:
    file_a = tmp_path / "a.md"
    file_a.write_text("alpha", encoding="utf-8")

    document = build_pager_document([str(file_a)])

    assert [section.identity for section in document.sections] == [f"file:{file_a}"]
    assert document.title == "1 file"
    assert document.origin is PagerOrigin.FILE
    assert document.link_context is not None
    assert document.sections[0].link_anchors[0].directory == tmp_path.resolve()


def test_build_pager_document_preserves_supplied_link_context(tmp_path: Path) -> None:
    file_a = tmp_path / "a.md"
    file_a.write_text("alpha", encoding="utf-8")
    context = LinkResolutionContext(anchors=(LinkAnchor(tmp_path),))

    document = build_pager_document([str(file_a)], link_context=context)

    assert document.link_context is context


def test_build_pager_document_prepends_commit_manifest_section(tmp_path: Path) -> None:
    file_a = tmp_path / "a.md"
    file_a.write_text("alpha", encoding="utf-8")
    spec = _commit_spec()

    document = build_pager_document([str(file_a)], [spec])

    assert len(document.sections) == 2
    commit_section = document.sections[0]
    assert commit_section.identity == "pager-commits"
    assert commit_section.kind == _COMMIT_TARGET_KIND
    assert commit_section.plain_text.startswith(spec.short_sha)
    (target,) = commit_section.targets
    assert target.kind == _COMMIT_TARGET_KIND
    assert target.target is spec
    assert document.sections[1].identity == f"file:{file_a}"


def test_commit_manifest_section_freezes_context_known_kinds(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    file_a = tmp_path / "a.md"
    file_a.write_text("alpha", encoding="utf-8")
    spec = replace(_commit_spec(), subject="feat: land designs:202609/spec.md")
    monkeypatch.setattr(
        "sase.ace.tui.actions.hints._files.known_kinds_from_link_context",
        lambda _context: ("designs",),
    )

    document = build_pager_document([str(file_a)], [spec])

    commit_section = document.sections[0]
    assert "designs" in commit_section.known_kinds
    assert "designs" in document.sections[1].known_kinds
    scanned = [
        (span.kind, span.text)
        for span in section_target_spans(commit_section, document.origin)
        if span.source == "scanned"
    ]
    assert scanned == [(LinkSpanKind.ARTIFACT_REF.value, "designs:202609/spec.md")]
