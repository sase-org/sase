"""Unavailable, ambiguous, filtered, and retryable rendered-link outcomes."""

from __future__ import annotations

from pathlib import Path

import pytest

from sase.artifact_ref_models import ArtifactRefDocumentOwner, ArtifactRefRepository
from sase.pager.adapters import document_from_paths
from sase.pager.app import SasePager
from sase.pager.document import PagerDocument, PagerSection
from sase.pager.link_context import merge_link_context
from sase.pager.resolve import resolve_link

from tests.pager._rendered_link_corpus import (
    ROUTER,
    build_corpus,
    forbid_checkout_allocation,
    install_inventory,
)
from tests.pager._rendered_link_pilot import (
    follow_display,
    install_clipboard,
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


async def test_failed_follow_leaves_the_document_and_trail_untouched(
    corpus,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = corpus.primary / "missing.md"
    source.write_text("see Sources/DoesNotExist.swift\n", encoding="utf-8")
    document = document_from_paths([source], cwd=corpus.cwd)
    app = SasePager(document)
    notifications = notify_capture(app)
    with forbid_checkout_allocation(monkeypatch):
        async with app.run_test(size=(80, 24)) as pilot:
            await settle(pilot)
            screen = pager_screen(app)
            await follow_display(pilot, "Sources/DoesNotExist.swift")
            assert screen.document is document
            assert screen._back_trail == []
            assert any("not found" in message for message, _severity in notifications)
            assert screen._label_layer is not None
            matching = [
                label
                for label in screen._label_layer.labels
                if label.target.text == "Sources/DoesNotExist.swift"
            ]
            assert matching


async def test_missing_checkout_is_retryable_and_refresh_clears_it(
    corpus, monkeypatch: pytest.MonkeyPatch
) -> None:
    absent = corpus.root / "absent-capture"
    source = corpus.primary / "pending.md"
    source.write_text(f"see {ROUTER}\n", encoding="utf-8")
    document = document_from_paths([source], cwd=corpus.cwd)
    section = document.sections[0]
    document = PagerDocument(
        sections=(
            PagerSection(
                identity=section.identity,
                title=section.title,
                kind=section.kind,
                body=section.body,
                subject_ref=section.subject_ref,
                link_anchors=section.link_anchors,
                owner=ArtifactRefDocumentOwner(
                    source_reference=section.identity,
                    source_directory=str(absent),
                    checkout_candidates=(absent,),
                ),
            ),
        ),
        title=document.title,
        origin=document.origin,
        link_context=document.link_context,
    )

    def fake_context(_workspace_dir, workspace_num=1, project=None):
        del workspace_num, project
        return corpus.context.__class__(
            document_roots=corpus.context.document_roots,
            chats_root=corpus.context.chats_root,
            artifact_index_path=corpus.context.artifact_index_path,
            repositories=(
                ArtifactRefRepository(
                    "bob-mac-capture", checkout_paths=(), kind="linked"
                ),
            ),
            projects=corpus.context.projects,
        )

    monkeypatch.setattr("sase.artifact_ref_context.artifact_ref_context", fake_context)
    monkeypatch.setattr(
        "sase.pager._resolve_artifact_refs.artifact_ref_context", fake_context
    )

    section = document.sections[0]
    context = merge_link_context(
        section.link_anchors, document.link_context, owner=section.owner
    )
    resolution = resolve_link(ROUTER, context=context)
    assert resolution.target is None
    assert resolution.retryable is True
    assert resolution.unresolved_message is not None

    app = SasePager(document)
    notifications = notify_capture(app)
    async with app.run_test(size=(80, 24)) as pilot:
        await settle(pilot)
        screen = pager_screen(app)
        await follow_display(pilot, ROUTER)
        assert screen.document is document
        assert notifications

        monkeypatch.setattr(
            "sase.artifact_ref_context.artifact_ref_context",
            lambda *_args, **_kwargs: corpus.context,
        )
        monkeypatch.setattr(
            "sase.pager._resolve_artifact_refs.artifact_ref_context",
            lambda *_args, **_kwargs: corpus.context,
        )
        restored = resolve_link(ROUTER, context=context)
        assert restored.target is not None, restored.unresolved_message
        await pilot.press("r")
        await settle(pilot)
        await follow_display(pilot, ROUTER)
        assert "struct Router" in screen.document.sections[0].plain_text


async def test_ambiguous_linked_repos_offer_followable_candidates(
    corpus, monkeypatch: pytest.MonkeyPatch
) -> None:
    twin = corpus.root / "twin-capture"
    twin_router = twin / ROUTER
    twin_router.parent.mkdir(parents=True)
    twin_router.write_text("twin router\n", encoding="utf-8")
    source = corpus.primary / "ambiguous.md"
    source.write_text(f"see {ROUTER}\n", encoding="utf-8")

    def fake_context(_workspace_dir, workspace_num=1, project=None):
        del workspace_num, project
        return corpus.context.__class__(
            document_roots=corpus.context.document_roots,
            chats_root=corpus.context.chats_root,
            artifact_index_path=corpus.context.artifact_index_path,
            repositories=(
                ArtifactRefRepository(
                    "bob-mac-capture",
                    checkout_paths=(corpus.capture,),
                    kind="linked",
                ),
                ArtifactRefRepository(
                    "twin-capture", checkout_paths=(twin,), kind="linked"
                ),
            ),
            projects=corpus.context.projects,
        )

    monkeypatch.setattr("sase.artifact_ref_context.artifact_ref_context", fake_context)
    monkeypatch.setattr(
        "sase.pager._resolve_artifact_refs.artifact_ref_context", fake_context
    )
    document = document_from_paths([source], cwd=corpus.cwd)
    app = SasePager(document)
    async with app.run_test(size=(80, 24)) as pilot:
        await settle(pilot)
        screen = pager_screen(app)
        await follow_display(pilot, ROUTER)
        body = screen.document.sections[0].plain_text
        assert str(corpus.router) in body
        assert str(twin_router) in body
        assert "ambiguous" in screen.document.title


async def test_filtered_plan_ref_stays_visible_with_a_filtered_reason(
    corpus, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = corpus.primary / "secret-link.md"
    source.write_text("see plan:202609/secret.md\n", encoding="utf-8")

    def fake_context(_workspace_dir, workspace_num=1, project=None):
        del workspace_num, project
        return corpus.filtered_context

    monkeypatch.setattr("sase.artifact_ref_context.artifact_ref_context", fake_context)
    monkeypatch.setattr(
        "sase.pager._resolve_artifact_refs.artifact_ref_context", fake_context
    )
    document = document_from_paths([source], cwd=corpus.cwd)
    app = SasePager(document)
    notifications = notify_capture(app)
    async with app.run_test(size=(80, 24)) as pilot:
        await settle(pilot)
        screen = pager_screen(app)
        await follow_display(pilot, "plan:202609/secret.md")
        assert screen.document is document
        assert screen._back_trail == []
        assert any("filter" in message.lower() for message, _ in notifications)


async def test_copy_of_a_missing_path_keeps_the_logical_token(
    corpus, monkeypatch: pytest.MonkeyPatch
) -> None:
    copied = install_clipboard(monkeypatch)
    source = corpus.primary / "missing.md"
    source.write_text("see Sources/DoesNotExist.swift\n", encoding="utf-8")
    document = document_from_paths([source], cwd=corpus.cwd)
    app = SasePager(document)
    async with app.run_test(size=(80, 24)) as pilot:
        await settle(pilot)
        screen = pager_screen(app)
        from tests.pager._rendered_link_pilot import label_for

        label = label_for(screen, "Sources/DoesNotExist.swift")
        await press_hint(pilot, "y" + label.hint)
        assert copied == ["Sources/DoesNotExist.swift"]
        assert screen.document is document


def test_unavailable_resolution_is_computed_without_a_second_search(corpus) -> None:
    source = corpus.primary / "missing.md"
    source.write_text("see Sources/DoesNotExist.swift\n", encoding="utf-8")
    document = document_from_paths([source], cwd=corpus.cwd)
    section = document.sections[0]
    context = merge_link_context(
        section.link_anchors, document.link_context, owner=section.owner
    )
    first = resolve_link("Sources/DoesNotExist.swift", context=context)
    second = resolve_link("Sources/DoesNotExist.swift", context=context)
    assert first.target is None
    assert first.unresolved_message == second.unresolved_message
    assert first.unresolved_message is not None
    assert (
        "not found" in first.unresolved_message
        or "unavailable" in first.unresolved_message
    )
