"""Tests for view-file pager request dispatch and context capture."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
import threading
from unittest.mock import MagicMock

import pytest

from sase.ace.tui.actions.hints._files import build_pager_document
from sase.ace.tui.actions.hints._link_context_capture import (
    CapturedLinkContext,
    link_context_from_capture,
)
from sase.ace.tui.artifact_reads import ArtifactReadRefSpec
from sase.pager.document import PagerDocument
from sase.pager.link_context import LinkAnchor, LinkResolutionContext

from ._view_files_helpers import _commit_spec, _make_app


async def test_dispatches_to_sase_pager_with_built_document(tmp_path: Path) -> None:
    notes = tmp_path / "notes.md"
    notes.write_text("hi", encoding="utf-8")
    app = _make_app(str(notes))
    app._view_files_with_pager_screen = MagicMock()  # type: ignore[method-assign]

    await app._process_view_input("1")

    app._view_files_with_pager_screen.assert_called_once()
    (document,) = app._view_files_with_pager_screen.call_args.args
    assert [section.identity for section in document.sections] == [f"file:{notes}"]


async def test_builds_the_document_off_the_event_loop_thread(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    notes = tmp_path / "notes.md"
    notes.write_text("hi", encoding="utf-8")
    app = _make_app(str(notes))
    app._view_files_with_pager_screen = MagicMock()  # type: ignore[method-assign]
    event_loop_thread = threading.get_ident()
    build_threads: list[int] = []
    real_build_pager_document = build_pager_document

    def spy(*args: object, **kwargs: object) -> PagerDocument:
        build_threads.append(threading.get_ident())
        return real_build_pager_document(*args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(
        "sase.ace.tui.actions.hints._view_processing.build_pager_document",
        spy,
    )

    await app._process_view_input("1")

    assert build_threads
    assert all(thread_id != event_loop_thread for thread_id in build_threads)


async def test_mixed_file_and_commit_selection_attaches_commit_section(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    notes = tmp_path / "notes.md"
    notes.write_text("hi", encoding="utf-8")
    spec = _commit_spec()
    app = _make_app(str(notes))
    app._hint_commit_views = {2: spec}
    app._view_files_with_pager_screen = MagicMock()  # type: ignore[method-assign]

    await app._process_view_input("1 2")

    # The existing eager commit-modal behavior (tested exhaustively in
    # test_view_files_commits.py) is untouched by the flag.
    app.app.push_screen.assert_called_once()
    app._view_files_with_pager_screen.assert_called_once()
    (document,) = app._view_files_with_pager_screen.call_args.args
    assert document.sections[0].identity == "pager-commits"
    assert document.sections[1].identity == f"file:{notes}"


async def test_missing_file_hint_warns_without_opening_pager(tmp_path: Path) -> None:
    missing = tmp_path / "missing.md"
    app = _make_app(str(missing))

    await app._process_view_input("1")

    app.push_screen.assert_not_called()
    app.notify.assert_any_call(
        f"File no longer exists: {missing}",
        severity="warning",
    )
    app.notify.assert_any_call(
        "No selected files could be opened",
        severity="warning",
    )


async def test_missing_file_hint_drops_only_the_stale_selection(
    tmp_path: Path,
) -> None:
    missing = tmp_path / "missing.md"
    notes = tmp_path / "notes.md"
    notes.write_text("hi", encoding="utf-8")
    app = _make_app(str(missing), str(notes))
    app._view_files_with_pager_screen = MagicMock()  # type: ignore[method-assign]

    await app._process_view_input("1 2")

    app.notify.assert_any_call(
        f"File no longer exists: {missing}",
        severity="warning",
    )
    app._view_files_with_pager_screen.assert_called_once()
    (document,) = app._view_files_with_pager_screen.call_args.args
    assert [section.identity for section in document.sections] == [f"file:{notes}"]


def test_prepare_view_input_snapshots_agent_inputs_without_building_context(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = _make_app("/tmp/notes.md")
    app.current_tab = "agents"
    agent = SimpleNamespace(
        effective_workspace_num=7,
        project_file="/tmp/project.sase",
        workspace_dir="/tmp/workspace",
    )
    app._get_selected_agent = lambda: agent  # type: ignore[method-assign]

    def boom(*_args: object, **_kwargs: object) -> object:
        raise AssertionError("ACE preparation must only snapshot agent inputs")

    monkeypatch.setattr(
        "sase.ace.tui.actions.hints._view_processing.link_context_from_capture",
        boom,
    )
    monkeypatch.setattr(
        "sase.ace.tui.actions.hints._link_context_capture.agent_link_context",
        boom,
    )
    monkeypatch.setattr(
        "sase.ace.tui.actions.hints._link_context_capture.workspace_link_context",
        boom,
    )
    monkeypatch.setattr(
        "sase.ace.tui.actions.hints._link_context_capture.default_link_context",
        boom,
    )

    prepared = app._prepare_view_input("1")

    assert prepared is not None
    assert prepared.request.captured_link_context == CapturedLinkContext(
        source="agent",
        workspace_num=7,
        project_file="/tmp/project.sase",
        workspace_dir="/tmp/workspace",
    )


def test_prepare_view_input_snapshots_patch_inputs_without_building_context(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch = SimpleNamespace(project_basename="proj")
    app = _make_app("/tmp/notes.md")
    app.current_tab = "patches"
    app.patches = [patch]
    app.current_idx = 0

    def boom(*_args: object, **_kwargs: object) -> object:
        raise AssertionError("ACE preparation must only snapshot patch inputs")

    monkeypatch.setattr(
        "sase.ace.tui.actions.hints._view_processing.link_context_from_capture",
        boom,
    )
    monkeypatch.setattr(
        "sase.ace.tui.actions.hints._link_context_capture.get_workspace_directory_for_patch",
        boom,
    )
    monkeypatch.setattr(
        "sase.ace.tui.actions.hints._link_context_capture.workspace_link_context",
        boom,
    )
    monkeypatch.setattr(
        "sase.ace.tui.actions.hints._link_context_capture.default_link_context",
        boom,
    )

    prepared = app._prepare_view_input("1")

    assert prepared is not None
    assert prepared.request.captured_link_context == CapturedLinkContext(
        source="patch",
        project_basename="proj",
    )


def test_link_context_from_capture_builds_agent_context(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = LinkResolutionContext()
    calls: list[tuple[int | None, str | None, str | None]] = []

    def fake_agent_context(
        workspace_num: int | None,
        project_file: str | None,
        workspace_dir: str | None,
    ) -> LinkResolutionContext:
        calls.append((workspace_num, project_file, workspace_dir))
        return context

    monkeypatch.setattr(
        "sase.ace.tui.actions.hints._link_context_capture.agent_link_context",
        fake_agent_context,
    )

    captured = CapturedLinkContext(
        source="agent",
        workspace_num=7,
        project_file="/tmp/project.sase",
        workspace_dir="/tmp/workspace",
    )

    assert link_context_from_capture(captured) is context
    assert calls == [(7, "/tmp/project.sase", "/tmp/workspace")]


def test_link_context_from_capture_builds_patch_context(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = LinkResolutionContext()
    patch_lookups: list[str] = []

    def fake_workspace_dir(patch: object) -> str | None:
        basename = getattr(patch, "project_basename", None)
        patch_lookups.append(str(basename))
        return "/tmp/patch-workspace" if basename == "proj" else None

    monkeypatch.setattr(
        "sase.ace.tui.actions.hints._link_context_capture.get_workspace_directory_for_patch",
        fake_workspace_dir,
    )
    monkeypatch.setattr(
        "sase.ace.tui.actions.hints._link_context_capture.workspace_link_context",
        lambda value: context if value == "/tmp/patch-workspace" else None,
    )

    captured = CapturedLinkContext(source="patch", project_basename="proj")

    assert link_context_from_capture(captured) is context
    assert patch_lookups == ["proj"]


async def test_view_link_context_is_built_off_the_event_loop(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    notes = tmp_path / "notes.md"
    notes.write_text("hi", encoding="utf-8")
    app = _make_app(str(notes))
    app.current_tab = "agents"
    app._get_selected_agent = lambda: SimpleNamespace(  # type: ignore[method-assign]
        effective_workspace_num=7,
        project_file="/tmp/project.sase",
        workspace_dir="/tmp/workspace",
    )
    app._view_files_with_pager_screen = MagicMock()  # type: ignore[method-assign]
    event_loop_thread = threading.get_ident()
    context_threads: list[int] = []
    captured_on_loop: list[CapturedLinkContext] = []

    def spy_from_capture(captured: CapturedLinkContext) -> LinkResolutionContext:
        context_threads.append(threading.get_ident())
        assert captured == CapturedLinkContext(
            source="agent",
            workspace_num=7,
            project_file="/tmp/project.sase",
            workspace_dir="/tmp/workspace",
        )
        return LinkResolutionContext(anchors=(LinkAnchor(tmp_path, workspace_num=7),))

    monkeypatch.setattr(
        "sase.ace.tui.actions.hints._view_processing.link_context_from_capture",
        spy_from_capture,
    )

    prepared = app._prepare_view_input("1")
    assert prepared is not None
    captured_on_loop.append(prepared.request.captured_link_context)
    assert not context_threads

    await app._process_view_input("1")

    assert captured_on_loop == [
        CapturedLinkContext(
            source="agent",
            workspace_num=7,
            project_file="/tmp/project.sase",
            workspace_dir="/tmp/workspace",
        )
    ]
    assert context_threads
    assert all(thread_id != event_loop_thread for thread_id in context_threads)
    app._view_files_with_pager_screen.assert_called_once()
    (document,) = app._view_files_with_pager_screen.call_args.args
    assert document.link_context is not None
    assert document.link_context.anchors[0].workspace_num == 7


async def test_pager_build_oserror_is_reported(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    notes = tmp_path / "notes.md"
    notes.write_text("hi", encoding="utf-8")
    app = _make_app(str(notes))
    app._view_files_with_pager_screen = MagicMock()  # type: ignore[method-assign]

    def fail_build(*_args: object, **_kwargs: object) -> PagerDocument:
        raise OSError("vanished")

    monkeypatch.setattr(
        "sase.ace.tui.actions.hints._view_processing.build_pager_document",
        fail_build,
    )

    await app._process_view_input("1")

    app._view_files_with_pager_screen.assert_not_called()
    app.notify.assert_any_call("Could not open pager: vanished", severity="error")


async def test_artifact_read_hint_recovery_opens_repaired_path(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    missing = tmp_path / "stale.md"
    recovered = tmp_path / "recovered.md"
    recovered.write_text("recovered", encoding="utf-8")
    spec = ArtifactReadRefSpec(
        ref="research:202608/design.md",
        cwd="/tmp/workspace",
    )
    app = _make_app(str(missing))
    app._hint_artifact_read_refs = {str(missing): spec}
    app._view_files_with_pager_screen = MagicMock()  # type: ignore[method-assign]
    calls: list[ArtifactReadRefSpec] = []

    def repair(value: ArtifactReadRefSpec) -> str | None:
        calls.append(value)
        return str(recovered)

    monkeypatch.setattr(
        "sase.ace.tui.actions.hints._view_processing.repair_artifact_read_path",
        repair,
    )

    await app._process_view_input("1")

    assert calls == [spec]
    app.notify.assert_not_called()
    app._view_files_with_pager_screen.assert_called_once()
    (document,) = app._view_files_with_pager_screen.call_args.args
    assert [section.identity for section in document.sections] == [f"file:{recovered}"]


async def test_artifact_read_hint_recovery_none_reports_missing(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    missing = tmp_path / "stale.md"
    spec = ArtifactReadRefSpec(
        ref="research:202608/design.md",
        cwd="/tmp/workspace",
    )
    app = _make_app(str(missing))
    app._hint_artifact_read_refs = {str(missing): spec}
    app._view_files_with_pager_screen = MagicMock()  # type: ignore[method-assign]
    monkeypatch.setattr(
        "sase.ace.tui.actions.hints._view_processing.repair_artifact_read_path",
        lambda _spec: None,
    )

    await app._process_view_input("1")

    app._view_files_with_pager_screen.assert_not_called()
    app.notify.assert_any_call(
        f"File no longer exists: {missing}",
        severity="warning",
    )
