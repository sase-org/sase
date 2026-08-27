"""Tests for the `link_pager`-gated `SasePager` dispatch in the view-file flow."""

from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
import threading
from unittest.mock import MagicMock

import pytest

from sase.ace.tui.actions.hints import _processing as processing_mod
from sase.ace.tui.actions.hints._files import (
    _COMMIT_TARGET_KIND,
    _handle_commit_attached_target,
    _resolve_ref_from_link_index,
    build_pager_document,
)
from sase.ace.tui.modals.commit_view_modal import CommitViewModal
from sase.core.artifact_entry_target import ArtifactEntryTarget
from sase.pager.document import (
    PagerDocument,
    PagerOrigin,
    PagerSection,
    PagerTargetSpan,
)
from sase.pager.resolve import LinkTarget, LinkTargetKind

from ._view_files_helpers import _commit_spec, _make_app


class _FakePager:
    def __init__(self) -> None:
        self.notify = MagicMock()
        self.push_screen = MagicMock()


def _target(spec: object, *, text: str = "abc1234") -> PagerTargetSpan:
    return PagerTargetSpan(
        kind=_COMMIT_TARGET_KIND,
        target=spec,
        start=0,
        end=len(text),
        text=text,
        source="attached",
    )


# -- build_pager_document -----------------------------------------------------


def test_build_pager_document_files_only_matches_document_from_paths(
    tmp_path: Path,
) -> None:
    file_a = tmp_path / "a.md"
    file_a.write_text("alpha", encoding="utf-8")

    document = build_pager_document([str(file_a)])

    assert [section.identity for section in document.sections] == [f"file:{file_a}"]
    assert document.title == "1 file"
    assert document.origin is PagerOrigin.FILE


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


# -- _finish_view_request dispatch --------------------------------------------


async def test_flag_off_dispatches_to_legacy_pager(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    notes = tmp_path / "notes.md"
    notes.write_text("hi", encoding="utf-8")
    app = _make_app(str(notes))
    app._view_files_with_pager = MagicMock()  # type: ignore[method-assign]
    app._view_files_with_sase_pager = MagicMock()  # type: ignore[method-assign]
    monkeypatch.setattr(processing_mod, "link_pager_enabled", lambda: False)

    await app._process_view_input("1")

    app._view_files_with_pager.assert_called_once_with([str(notes)])
    app._view_files_with_sase_pager.assert_not_called()


async def test_flag_on_dispatches_to_sase_pager_with_built_document(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    notes = tmp_path / "notes.md"
    notes.write_text("hi", encoding="utf-8")
    app = _make_app(str(notes))
    app._view_files_with_pager = MagicMock()  # type: ignore[method-assign]
    app._view_files_with_sase_pager = MagicMock()  # type: ignore[method-assign]
    monkeypatch.setattr(processing_mod, "link_pager_enabled", lambda: True)

    await app._process_view_input("1")

    app._view_files_with_pager.assert_not_called()
    app._view_files_with_sase_pager.assert_called_once()
    (document,) = app._view_files_with_sase_pager.call_args.args
    assert [section.identity for section in document.sections] == [f"file:{notes}"]


async def test_flag_on_builds_the_document_off_the_event_loop_thread(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    notes = tmp_path / "notes.md"
    notes.write_text("hi", encoding="utf-8")
    app = _make_app(str(notes))
    app._view_files_with_sase_pager = MagicMock()  # type: ignore[method-assign]
    monkeypatch.setattr(processing_mod, "link_pager_enabled", lambda: True)
    event_loop_thread = threading.get_ident()
    build_threads: list[int] = []
    real_build_pager_document = build_pager_document

    def spy(*args: object, **kwargs: object) -> PagerDocument:
        build_threads.append(threading.get_ident())
        return real_build_pager_document(*args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(processing_mod, "build_pager_document", spy)

    await app._process_view_input("1")

    assert build_threads
    assert all(thread_id != event_loop_thread for thread_id in build_threads)


async def test_flag_on_mixed_file_and_commit_selection_attaches_commit_section(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    notes = tmp_path / "notes.md"
    notes.write_text("hi", encoding="utf-8")
    spec = _commit_spec()
    app = _make_app(str(notes))
    app._hint_commit_views = {2: spec}
    app._view_files_with_sase_pager = MagicMock()  # type: ignore[method-assign]
    monkeypatch.setattr(processing_mod, "link_pager_enabled", lambda: True)

    await app._process_view_input("1 2")

    # The existing eager commit-modal behavior (tested exhaustively in
    # test_view_files_commits.py) is untouched by the flag.
    app.app.push_screen.assert_called_once()
    app._view_files_with_sase_pager.assert_called_once()
    (document,) = app._view_files_with_sase_pager.call_args.args
    assert document.sections[0].identity == "pager-commits"
    assert document.sections[1].identity == f"file:{notes}"


# -- SasePager wiring ----------------------------------------------------------


def test_view_files_with_sase_pager_runs_under_suspend(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    document = PagerDocument(
        sections=(
            PagerSection(
                identity="file:/tmp/a.py", title="a.py", kind="file", body="hi\n"
            ),
        ),
        title="1 file",
        origin=PagerOrigin.FILE,
    )
    captured: dict[str, object] = {}

    class _FakeSasePager:
        def __init__(
            self,
            doc: PagerDocument,
            *,
            attached_handlers=None,
            resolve_ref_fn=None,
        ) -> None:
            captured["document"] = doc
            captured["handlers"] = attached_handlers
            captured["resolve_ref_fn"] = resolve_ref_fn

        def run(self) -> None:
            captured["ran"] = True

    monkeypatch.setattr("sase.ace.tui.actions.hints._files.SasePager", _FakeSasePager)
    app = _make_app()

    app._view_files_with_sase_pager(document)

    assert app.suspend_recorder.entered
    assert captured["document"] is document
    assert captured["ran"] is True
    assert _COMMIT_TARGET_KIND in captured["handlers"]  # type: ignore[operator]
    assert callable(captured["resolve_ref_fn"])


def test_link_index_backed_pager_resolver_prefers_indexed_file_target(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    path = tmp_path / "indexed.md"
    path.write_text("indexed\n", encoding="utf-8")
    ref = f"file:{path}"

    class _Index:
        targets_by_ref = {ref: ArtifactEntryTarget("files", (str(path),))}

        def target_for(self, value: str) -> ArtifactEntryTarget | None:
            return self.targets_by_ref[value]

    class _App:
        _link_index = _Index()

    monkeypatch.setattr(
        "sase.ace.tui.actions.hints._files.resolve_ref",
        lambda value: (_ for _ in ()).throw(AssertionError(value)),
    )

    target = _resolve_ref_from_link_index(_App(), ref)

    assert target is not None
    assert target.kind is LinkTargetKind.DOCUMENT
    assert target.document is not None
    assert target.document.sections[0].plain_text == "indexed\n"


def test_link_index_backed_pager_resolver_falls_back_for_unknown_ref(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fallback = LinkTarget(kind=LinkTargetKind.DOCUMENT)

    class _Index:
        targets_by_ref: dict[str, ArtifactEntryTarget | None] = {}

        def target_for(self, value: str) -> ArtifactEntryTarget | None:
            raise AssertionError(value)

    class _App:
        _link_index = _Index()

    monkeypatch.setattr(
        "sase.ace.tui.actions.hints._files.resolve_ref",
        lambda value: fallback if value == "bead:unknown" else None,
    )

    assert _resolve_ref_from_link_index(_App(), "bead:unknown") is fallback


# -- _handle_commit_attached_target --------------------------------------------


def test_commit_attached_target_copy_copies_the_sha(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pager = _FakePager()
    spec = _commit_spec(sha="abcdef1234567890")
    calls: list[tuple[object, ...]] = []
    monkeypatch.setattr(
        "sase.ace.tui.actions.hints._files.schedule_copy_delivery",
        lambda owner, value, **kwargs: calls.append((owner, value, kwargs)),
    )

    _handle_commit_attached_target(pager, _target(spec), "copy")  # type: ignore[arg-type]

    assert calls == [
        (
            pager,
            spec.sha,
            {"copied_label": "commit SHA", "task_name": "sase-pager-copy-commit"},
        )
    ]


def test_commit_attached_target_edit_opens_editor_with_diff_path(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    pager = _FakePager()
    diff_path = tmp_path / "commit.diff"
    spec = _commit_spec(diff_path=str(diff_path))
    run_calls: list[list[str]] = []
    monkeypatch.setattr(
        "sase.ace.tui.actions.hints._files.subprocess.run",
        lambda argv, **kwargs: run_calls.append(list(argv)),
    )
    monkeypatch.setenv("EDITOR", "nvim")

    @contextmanager
    def fake_suspend(_app: object, **_metadata: object):
        yield

    monkeypatch.setattr(
        "sase.ace.tui.actions.hints._files.suspend_for_external_tool", fake_suspend
    )

    _handle_commit_attached_target(pager, _target(spec), "edit")  # type: ignore[arg-type]

    assert run_calls == [["nvim", str(diff_path)]]


def test_commit_attached_target_edit_without_diff_path_warns() -> None:
    pager = _FakePager()
    spec = _commit_spec()

    _handle_commit_attached_target(pager, _target(spec), "edit")  # type: ignore[arg-type]

    pager.notify.assert_called_once()
    assert "No raw diff path" in pager.notify.call_args.args[0]


def test_commit_attached_target_follow_opens_commit_view_modal() -> None:
    pager = _FakePager()
    spec = _commit_spec()

    _handle_commit_attached_target(pager, _target(spec), "follow")  # type: ignore[arg-type]

    pager.push_screen.assert_called_once()
    modal = pager.push_screen.call_args.args[0]
    assert isinstance(modal, CommitViewModal)
    assert modal._commit_specs == (spec,)
