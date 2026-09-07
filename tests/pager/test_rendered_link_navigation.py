"""Navigation, isolation, reload, and attached-target contract tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from sase.pager.adapters import document_from_paths, path_section
from sase.pager.app import SasePager
from sase.pager.document import (
    AttachedTarget,
    PagerDocument,
    PagerOrigin,
    PagerSection,
    PagerTargetSpan,
)
from tests.pager._rendered_link_corpus import (
    CONTROLLER,
    ROUTER,
    build_corpus,
    install_inventory,
    owner_for_checkout,
)
from tests.pager._rendered_link_pilot import (
    follow_display,
    install_media,
    label_for,
    notify_capture,
    pager_screen,
    press_hint,
    settle,
)


@pytest.fixture
def corpus(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    built = build_corpus(tmp_path)
    install_inventory(monkeypatch, built)
    return built


def _screenshot_document(corpus) -> PagerDocument:
    return document_from_paths([corpus.screenshot_plan], cwd=corpus.cwd)


async def test_follow_several_hops_then_back_and_forward_restore_the_trail(
    corpus,
) -> None:
    document = _screenshot_document(corpus)
    app = SasePager(document)
    async with app.run_test(size=(120, 40)) as pilot:
        await settle(pilot)
        screen = pager_screen(app)
        await follow_display(pilot, ROUTER)
        assert "struct Router" in screen.document.sections[0].plain_text
        await follow_display(pilot, CONTROLLER)
        assert "struct Controller" in screen.document.sections[0].plain_text
        assert len(screen._back_trail) == 2

        await pilot.press("backspace")
        await settle(pilot)
        assert "struct Router" in screen.document.sections[0].plain_text
        await pilot.press("backspace")
        await settle(pilot)
        assert screen.document is document

        await pilot.press("ctrl+i")
        await settle(pilot)
        assert "struct Router" in screen.document.sections[0].plain_text
        await pilot.press("ctrl+i")
        await settle(pilot)
        assert "struct Controller" in screen.document.sections[0].plain_text


async def test_same_text_in_two_projects_is_section_isolated(corpus) -> None:
    body = "see src/shared.py\n"
    first = PagerSection(
        identity="file:primary",
        title="primary.md",
        kind="file",
        body=body,
        owner=owner_for_checkout(corpus.primary, source_reference="file:primary"),
        link_anchors=path_section(corpus.shared_primary).link_anchors,
    )
    second = PagerSection(
        identity="file:other",
        title="other.md",
        kind="file",
        body=body,
        owner=owner_for_checkout(corpus.other, source_reference="file:other"),
        link_anchors=path_section(corpus.shared_other).link_anchors,
        origin=PagerOrigin.FILE,
    )
    document = PagerDocument(
        sections=(first, second),
        title="2 files",
        origin=PagerOrigin.FILE,
    )
    app = SasePager(document)
    async with app.run_test(size=(120, 40)) as pilot:
        await settle(pilot)
        screen = pager_screen(app)
        labels = [
            label
            for label in screen._label_layer.labels  # type: ignore[union-attr]
            if label.target.text == "src/shared.py"
        ]
        assert [label.section_index for label in labels] == [0, 1]

        await press_hint(pilot, labels[0].hint)
        assert screen.document.sections[0].plain_text == "from-primary\n"
        await pilot.press("backspace")
        await settle(pilot)

        await press_hint(pilot, labels[1].hint)
        assert screen.document.sections[0].plain_text == "from-other\n"


async def test_mixed_origin_inputs_keep_diff_sha_and_file_path_rules(
    corpus,
) -> None:
    diff = PagerSection(
        identity="diff:head",
        title="HEAD",
        kind="diff",
        body="commit deadbee1 landed\n",
        origin=PagerOrigin.DIFF,
        owner=owner_for_checkout(corpus.primary, source_reference="diff:head"),
    )
    file_section = path_section(corpus.kitchen_sink, cwd=corpus.cwd)
    document = PagerDocument(
        sections=(diff, file_section),
        title="2 inputs",
        origin=PagerOrigin.FILE,
    )
    app = SasePager(document)
    notifications = notify_capture(app)
    async with app.run_test(size=(120, 48)) as pilot:
        await settle(pilot)
        screen = pager_screen(app)
        sha = next(
            label
            for label in screen._label_layer.labels  # type: ignore[union-attr]
            if label.target.text == "deadbee1"
        )
        assert sha.section_index == 0
        notifications.clear()
        trail = list(screen._back_trail)
        await press_hint(pilot, sha.hint)
        assert screen.document is document
        assert list(screen._back_trail) == trail
        assert notifications
        naive = label_for(screen, "@src/naïve.md")
        assert naive.section_index == 1
        await press_hint(pilot, naive.hint)
        assert "naive notes" in screen.document.sections[0].plain_text


async def test_reload_allows_a_previously_missing_target_to_resolve(corpus) -> None:
    later = corpus.capture / "Sources" / "BobMacCapture" / "CreatedLater.swift"
    source = corpus.primary / "pending.md"
    source.write_text(
        "see Sources/BobMacCapture/CreatedLater.swift\n", encoding="utf-8"
    )
    document = document_from_paths([source], cwd=corpus.cwd)
    app = SasePager(document)
    notifications = notify_capture(app)
    async with app.run_test(size=(120, 40)) as pilot:
        await settle(pilot)
        screen = pager_screen(app)
        await follow_display(pilot, "Sources/BobMacCapture/CreatedLater.swift")
        assert screen.document is document
        assert any(
            "not found" in message or "unavailable" in message
            for message, _ in notifications
        )

        later.write_text("created later\n", encoding="utf-8")
        await pilot.press("r")
        await settle(pilot)
        await follow_display(pilot, "Sources/BobMacCapture/CreatedLater.swift")
        assert "created later" in screen.document.sections[0].plain_text


async def test_media_press_returns_to_the_same_document(
    corpus, monkeypatch: pytest.MonkeyPatch
) -> None:
    views = install_media(monkeypatch)
    document = document_from_paths([corpus.kitchen_sink], cwd=corpus.cwd)
    app = SasePager(document)
    async with app.run_test(size=(120, 48)) as pilot:
        await settle(pilot)
        await follow_display(pilot, "docs/assets/dot.png")
        assert views
        assert pager_screen(app).document is document


async def test_attached_target_keeps_object_identity_and_skips_the_resolver(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = object()
    body = "commit!\n"
    section = PagerSection(
        identity="pager-commits",
        title="commits",
        kind="commit",
        body=body,
        targets=(AttachedTarget(kind="commit", target=payload, start=0, end=6),),
    )
    document = PagerDocument(
        sections=(section,), title="commits", origin=PagerOrigin.FILE
    )
    seen: list[tuple[object, str]] = []

    def handler(span: PagerTargetSpan, action: str) -> None:
        seen.append((span.target, action))

    def boom(*_args: object, **_kwargs: object) -> object:
        raise AssertionError("attached targets must not call resolve_ref")

    monkeypatch.setattr("sase.pager.screen.resolve_ref", boom)
    app = SasePager(document, attached_handlers={"commit": handler})
    async with app.run_test(size=(80, 24)) as pilot:
        await settle(pilot)
        await follow_display(pilot, "commit")
        await press_hint(pilot, "y" + label_for(pager_screen(app), "commit").hint)
    assert seen[0][0] is payload
    assert seen[0][1] == "follow"
    assert seen[1][0] is payload
    assert seen[1][1] == "copy"


async def test_links_never_paints_no_labels_and_does_not_follow() -> None:
    section = PagerSection(
        identity="file:links",
        title="links",
        kind="file",
        body="https://example.test/never\n",
    )
    document = PagerDocument(
        sections=(section,), title="links", origin=PagerOrigin.FILE
    )
    app = SasePager(document, links_enabled=False)
    async with app.run_test(size=(80, 24)) as pilot:
        await settle(pilot)
        screen = pager_screen(app)
        assert screen._label_layer is not None
        assert screen._label_layer.labels == ()
        await pilot.press("0")
        await settle(pilot)
        assert screen.document is document
