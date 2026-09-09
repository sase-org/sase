"""Scanner-to-action contract tests for the screenshot and kitchen-sink corpus.

Documents are built through production adapters. Labels are real. Presses go
through Textual Pilot into the real resolver — never an unconditional
``LinkTarget`` stub.
"""

from __future__ import annotations

import threading
from pathlib import Path

import pytest

from sase.pager.adapters import document_from_paths
from sase.pager.app import SasePager
from sase.pager.document import PagerDocument, target_resolution_ref
from sase.pager.link_context import merge_link_context
from sase.pager.resolve import resolve_link
from sase.pager.targets import LinkTargetKind

from tests.pager._rendered_link_corpus import (
    CONTROLLER,
    ROUTER,
    assert_expected_rendered,
    build_corpus,
    forbid_checkout_allocation,
    install_inventory,
    kitchen_expected,
    screenshot_expected,
)
from tests.pager._rendered_link_pilot import (
    follow_display,
    install_clipboard,
    install_editor,
    install_media,
    label_for,
    notify_capture,
    pager_screen,
    press_hint,
    settle,
    wait_for_notification,
)


@pytest.fixture
def corpus(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    built = build_corpus(tmp_path)
    install_inventory(monkeypatch, built)
    return built


def _screenshot_document(corpus) -> PagerDocument:
    return document_from_paths([corpus.screenshot_plan], cwd=corpus.cwd)


def _kitchen_document(corpus) -> PagerDocument:
    return document_from_paths([corpus.kitchen_sink], cwd=corpus.cwd)


def test_screenshot_scanner_emits_every_independently_declared_target(corpus) -> None:
    document = _screenshot_document(corpus)
    assert_expected_rendered(document, screenshot_expected(corpus))


def test_kitchen_scanner_emits_every_independently_declared_target(corpus) -> None:
    document = _kitchen_document(corpus)
    assert_expected_rendered(document, kitchen_expected(corpus))


def test_screenshot_source_is_absent_from_the_primary_git_tree(corpus) -> None:
    assert not (corpus.primary / ROUTER).exists()
    assert (corpus.cwd / ROUTER).is_file()
    assert not (corpus.primary / ".git" / "index").exists()
    assert corpus.router.is_file()
    assert corpus.router.read_text(encoding="utf-8").startswith("struct Router")


async def test_screenshot_plan_and_capture_paths_follow_through_real_labels(
    corpus,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    git_calls: list[Path] = []
    loop_thread = threading.current_thread()
    resolve_threads: list[int | None] = []
    real_git = __import__(
        "sase.pager._resolve_path_search", fromlist=["_git_ls_files"]
    )._git_ls_files

    def spy_git(directory: Path) -> tuple[str, ...] | None:
        git_calls.append(directory)
        return real_git(directory)

    def spy_resolve(ref: str, *, context=None):
        resolve_threads.append(threading.current_thread().ident)
        return resolve_link(ref, context=context)

    monkeypatch.setattr("sase.pager._resolve_path_search._git_ls_files", spy_git)
    monkeypatch.setattr("sase.pager.screen.resolve_ref", spy_resolve)
    with forbid_checkout_allocation(monkeypatch):
        document = _screenshot_document(corpus)
        expected = screenshot_expected(corpus)
        app = SasePager(document)
        async with app.run_test(size=(120, 40)) as pilot:
            await settle(pilot)
            screen = pager_screen(app)
            for occurrence in expected:
                if occurrence.outcome != "document":
                    continue
                label = label_for(screen, occurrence.display)
                before = len(resolve_threads)
                await press_hint(pilot, label.hint)
                assert screen.document is not document
                body = screen.document.sections[0].plain_text
                for snippet in occurrence.body_contains:
                    assert snippet in body
                if occurrence.identity_contains is not None:
                    assert occurrence.identity_contains in (
                        screen.document.sections[0].identity
                        + screen.document.sections[0].plain_text
                        + (screen.document.sections[0].subject_ref or "")
                    )
                assert resolve_threads[before:]
                assert resolve_threads[before] != loop_thread.ident
                await pilot.press("backspace")
                await settle(pilot)
                assert screen.document is document
            assert git_calls == []


async def test_screenshot_hosted_urls_copy_the_exact_destination(
    corpus,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    copied = install_clipboard(monkeypatch)
    document = _screenshot_document(corpus)
    app = SasePager(document)
    async with app.run_test(size=(120, 40)) as pilot:
        await settle(pilot)
        for occurrence in screenshot_expected(corpus):
            if occurrence.outcome != "url_copy":
                continue
            copied.clear()
            await follow_display(pilot, occurrence.display)
            assert copied == [occurrence.copy_text]
            assert pager_screen(app).document is document


async def test_screenshot_copy_and_edit_use_the_same_owned_targets(
    corpus,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    copied = install_clipboard(monkeypatch)
    runs = install_editor(monkeypatch)
    document = _screenshot_document(corpus)
    app = SasePager(document)
    async with app.run_test(size=(120, 40)) as pilot:
        await settle(pilot)
        screen = pager_screen(app)
        router = label_for(screen, ROUTER)
        await press_hint(pilot, "y" + router.hint)
        assert copied == [str(corpus.router)]
        assert screen.document is document

        await press_hint(pilot, "E" + router.hint)
        editor_runs = [argv for argv in runs if argv and argv[0] == "nvim"]
        assert editor_runs
        assert str(corpus.router) in editor_runs[-1]
        assert screen.document is document

        controller = label_for(screen, CONTROLLER)
        copied.clear()
        await press_hint(pilot, "y" + controller.hint)
        assert copied == [str(corpus.controller)]


async def test_kitchen_follow_copy_edit_and_media_for_each_supported_action(
    corpus,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    copied = install_clipboard(monkeypatch)
    runs = install_editor(monkeypatch)
    views = install_media(monkeypatch)
    document = _kitchen_document(corpus)
    expected = kitchen_expected(corpus)
    app = SasePager(document)
    notifications = notify_capture(app)
    async with app.run_test(size=(120, 48)) as pilot:
        await settle(pilot)
        screen = pager_screen(app)
        for occurrence in expected:
            label = label_for(screen, occurrence.display)
            if occurrence.outcome == "url_copy":
                copied.clear()
                await press_hint(pilot, label.hint)
                assert copied == [occurrence.copy_text]
                assert screen.document is document
                continue
            if occurrence.outcome == "media":
                views.clear()
                await press_hint(pilot, label.hint)
                assert views
                assert screen.document is document
                continue
            if occurrence.outcome == "unavailable":
                notifications.clear()
                trail = list(screen._back_trail)
                await press_hint(pilot, label.hint)
                assert screen.document is document
                assert list(screen._back_trail) == trail
                unavailable_fragment = occurrence.unavailable_contains
                await wait_for_notification(
                    pilot,
                    notifications,
                    lambda message, _severity, fragment=unavailable_fragment: (
                        fragment in message
                    ),
                )
                continue
            if occurrence.outcome != "document":
                continue
            await press_hint(pilot, label.hint)
            body = screen.document.sections[0].plain_text
            for snippet in occurrence.body_contains:
                assert snippet in body
            await pilot.press("backspace")
            await settle(pilot)
            assert screen.document is document

            if occurrence.copy_text is not None:
                copied.clear()
                await press_hint(pilot, "y" + label.hint)
                assert copied == [occurrence.copy_text]
            if occurrence.line is not None or occurrence.column is not None:
                runs.clear()
                await press_hint(pilot, "E" + label.hint)
                editor_runs = [argv for argv in runs if argv and argv[0] == "nvim"]
                assert editor_runs
                joined = " ".join(editor_runs[-1])
                if occurrence.line is not None:
                    assert str(occurrence.line) in joined
                edit_path = occurrence.edit_path or occurrence.copy_text
                if edit_path is not None:
                    assert edit_path in editor_runs[-1]


def test_owned_lookup_does_not_take_the_cwd_decoy(corpus) -> None:
    document = _screenshot_document(corpus)
    section = document.sections[0]
    context = merge_link_context(
        section.link_anchors, document.link_context, owner=section.owner
    )
    occurrence = next(
        item for item in screenshot_expected(corpus) if item.display == ROUTER
    )
    span = next(
        item
        for item in __import__(
            "sase.pager.document", fromlist=["section_target_spans"]
        ).section_target_spans(section, document.origin)
        if item.text == ROUTER
    )
    ref = target_resolution_ref(span, document.origin)
    assert ref == occurrence.resolution_ref
    resolution = resolve_link(ref, context=context)
    assert resolution.target is not None
    assert resolution.target.kind is LinkTargetKind.DOCUMENT
    assert resolution.target.edit_path == corpus.router
    assert resolution.target.document is not None
    assert "struct Router" in resolution.target.document.sections[0].plain_text
    assert "DECOY" not in resolution.target.document.sections[0].plain_text
