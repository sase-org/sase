"""ACE view-files pager contract: production adapters and real resolution."""

from __future__ import annotations

from pathlib import Path

import pytest

from sase.ace.tui.actions.hints._files import build_pager_document
from sase.core.artifact_entry_target import ArtifactEntryTarget
from sase.pager.app import SasePager
from sase.pager.link_context import LinkAnchor, LinkResolutionContext
from sase.pager.resolve import link_target_for_artifact_entry_target
from sase.pager.targets import LinkTargetKind

from tests.pager._rendered_link_corpus import (
    ROUTER,
    assert_expected_rendered,
    build_corpus,
    install_inventory,
    screenshot_expected,
)
from tests.pager._rendered_link_pilot import follow_display, pager_screen, settle


@pytest.fixture
def corpus(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    built = build_corpus(tmp_path)
    install_inventory(monkeypatch, built)
    return built


def test_ace_build_pager_document_keeps_screenshot_targets_and_owner(corpus) -> None:
    document = build_pager_document([str(corpus.screenshot_plan)])
    assert_expected_rendered(document, screenshot_expected(corpus))
    section = document.sections[0]
    assert section.owner is not None
    assert section.owner.source_reference is not None
    assert section.link_anchors
    assert section.link_anchors[0].directory == corpus.screenshot_plan.parent.resolve()


async def test_ace_built_document_follows_a_linked_capture_source(corpus) -> None:
    document = build_pager_document([str(corpus.screenshot_plan)])
    app = SasePager(document)
    async with app.run_test(size=(120, 40)) as pilot:
        await settle(pilot)
        await follow_display(pilot, ROUTER)
        screen = pager_screen(app)
        assert "struct Router" in screen.document.sections[0].plain_text
        assert "DECOY" not in screen.document.sections[0].plain_text


def test_link_index_fast_path_opens_a_real_file_with_supplied_context(
    corpus,
) -> None:
    context = LinkResolutionContext(
        anchors=(LinkAnchor(directory=corpus.capture),),
    )
    target = ArtifactEntryTarget("files", (str(corpus.router),))
    result = link_target_for_artifact_entry_target(
        f"file:{corpus.router}",
        target,
        context=context,
    )
    assert result is not None
    assert result.kind is LinkTargetKind.DOCUMENT
    assert result.document is not None
    assert result.document.sections[0].plain_text.startswith("struct Router")
    assert result.document.link_context is not None
    assert result.document.link_context.owner is not None
