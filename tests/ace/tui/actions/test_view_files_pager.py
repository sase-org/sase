"""Tests for `PagerScreen` dispatch in the view-file flow."""

from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
import threading
from unittest.mock import MagicMock

import pytest
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import VerticalScroll
from textual.widgets import Static

from sase.ace.tui.artifact_reads import ArtifactReadRefSpec
from sase.ace.tui.actions.hints._files import (
    _COMMIT_TARGET_KIND,
    FileViewingMixin,
    _handle_commit_attached_target,
    _resolve_ref_from_link_index,
    build_pager_document,
)
from sase.ace.tui.actions.hints._processing import InputProcessingMixin
from sase.ace.tui.modals.commit_view_modal import CommitViewModal
from sase.core.artifact_entry_target import ArtifactEntryTarget
from sase.pager import PagerExit, PagerScreen
from sase.pager.document import (
    AttachedTarget,
    PagerDocument,
    PagerOrigin,
    PagerSection,
    PagerTargetSpan,
)
from sase.pager.resolve import LinkTarget, LinkTargetKind

from ._view_files_helpers import _commit_spec, _make_app


class _FakeScreen:
    def __init__(self) -> None:
        self.notify = MagicMock()
        self.app = SimpleNamespace(push_screen=MagicMock())


class _PagerHost(App[None]):
    """Minimal Textual host used to exercise nested pager-screen behavior."""

    BINDINGS = [Binding("a", "host_a", "Host A", show=False)]

    def __init__(self) -> None:
        super().__init__()
        self.dismissed: list[PagerExit] = []
        self.host_a_count = 0

    def compose(self) -> ComposeResult:
        yield Static("host")

    def action_host_a(self) -> None:
        self.host_a_count += 1


class _ViewHost(InputProcessingMixin, FileViewingMixin, App[None]):
    """A real Textual host for the ACE view-file mixins."""

    def __init__(self, hint_mappings: dict[int, str]) -> None:
        super().__init__()
        self._hint_mappings = hint_mappings
        self._hint_tool_call_reports = {}
        self._hint_glossary_reports = {}
        self._hint_memory_reports = {}
        self._hint_artifact_read_refs = {}
        self._hint_commit_views = {}
        self._hint_patch_name = "cs"

    def compose(self) -> ComposeResult:
        yield Static("host")


def _target(spec: object, *, text: str = "abc1234") -> PagerTargetSpan:
    return PagerTargetSpan(
        kind=_COMMIT_TARGET_KIND,
        target=spec,
        start=0,
        end=len(text),
        text=text,
        source="attached",
    )


def _multi_section_document() -> PagerDocument:
    sections = tuple(
        PagerSection(
            identity=f"file:/tmp/{name}.py",
            title=f"{name}.py",
            kind="file",
            body="\n".join(f"{name} line {index}" for index in range(12)) + "\n",
        )
        for name in ("alpha", "beta")
    )
    return PagerDocument(sections=sections, title="2 files", origin=PagerOrigin.FILE)


def _attached_label_document(count: int) -> PagerDocument:
    lines: list[str] = []
    targets: list[AttachedTarget] = []
    offset = 0
    for index in range(count):
        label = f"commit{index:02d}"
        line = f"{label} subject {index}"
        targets.append(
            AttachedTarget(
                kind=_COMMIT_TARGET_KIND,
                target=f"target-{index}",
                start=offset,
                end=offset + len(label),
            )
        )
        lines.append(line)
        offset += len(line) + 1
    section = PagerSection(
        identity="pager-commits",
        title="Selected commits",
        kind=_COMMIT_TARGET_KIND,
        body="\n".join(lines) + "\n",
        targets=tuple(targets),
    )
    return PagerDocument(sections=(section,), title="commits", origin=PagerOrigin.FILE)


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
        "sase.ace.tui.actions.hints._processing.build_pager_document",
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
        "sase.ace.tui.actions.hints._processing.build_pager_document",
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
        "sase.ace.tui.actions.hints._processing.repair_artifact_read_path",
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
        "sase.ace.tui.actions.hints._processing.repair_artifact_read_path",
        lambda _spec: None,
    )

    await app._process_view_input("1")

    app._view_files_with_pager_screen.assert_not_called()
    app.notify.assert_any_call(
        f"File no longer exists: {missing}",
        severity="warning",
    )


# -- PagerScreen wiring --------------------------------------------------------


def test_view_files_with_pager_screen_pushes_screen_without_suspend(
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

    class _FakePagerScreen:
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
            captured["screen"] = self

    monkeypatch.setattr(
        "sase.ace.tui.actions.hints._files.PagerScreen", _FakePagerScreen
    )
    app = _make_app()

    app._view_files_with_pager_screen(document)

    app.push_screen.assert_called_once_with(captured["screen"])
    assert not app.suspend_recorder.entered
    assert captured["document"] is document
    assert _COMMIT_TARGET_KIND in captured["handlers"]  # type: ignore[operator]
    assert callable(captured["resolve_ref_fn"])


def test_view_files_with_pager_screen_toasts_when_push_fails() -> None:
    document = PagerDocument(
        sections=(
            PagerSection(
                identity="file:/tmp/a.py", title="a.py", kind="file", body="hi\n"
            ),
        ),
        title="1 file",
        origin=PagerOrigin.FILE,
    )
    app = _make_app()
    app.push_screen.side_effect = RuntimeError("boom")

    app._view_files_with_pager_screen(document)

    app.notify.assert_called_once_with("Could not open pager: boom", severity="error")


async def test_pager_screen_runs_inside_an_existing_textual_app() -> None:
    app = _PagerHost()
    async with app.run_test(size=(80, 10)) as pilot:
        screen = PagerScreen(_multi_section_document())
        app.push_screen(screen, callback=app.dismissed.append)
        await pilot.pause()

        assert app.is_running
        assert app.screen is screen
        scroll = screen.query_one("#pager-body-scroll", VerticalScroll)

        await pilot.press("j")
        await pilot.pause()
        assert scroll.scroll_y == 1

        await pilot.press("ctrl+n")
        await pilot.pause()
        assert scroll.scroll_y > 1

        await pilot.press("q")
        await pilot.pause()

        assert app.is_running
        assert app.screen is not screen
        assert app.dismissed == [PagerExit()]


async def test_view_request_pushes_real_pager_screen_inside_running_host(
    tmp_path: Path,
) -> None:
    notes = tmp_path / "notes.md"
    notes.write_text("hi", encoding="utf-8")
    app = _ViewHost({1: str(notes)})

    async with app.run_test(size=(80, 10)) as pilot:
        await app._process_view_input("1")
        await pilot.pause()

        assert isinstance(app.screen, PagerScreen)
        assert app.screen.document.sections[0].identity == f"file:{notes}"


async def test_pager_screen_modal_label_key_does_not_reach_host_binding() -> None:
    app = _PagerHost()
    handled: list[tuple[object, str]] = []
    async with app.run_test(size=(80, 12)) as pilot:
        screen = PagerScreen(
            _attached_label_document(11),
            attached_handlers={
                _COMMIT_TARGET_KIND: lambda target, action: handled.append(
                    (target.target, action)
                )
            },
        )
        app.push_screen(screen)
        await pilot.pause()

        await pilot.press("a")
        await pilot.pause()

        assert screen._last_activated_label is not None
        assert screen._last_activated_label.hint == "a"
        assert handled == [("target-10", "follow")]
        assert app.host_a_count == 0


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
    screen = _FakeScreen()
    spec = _commit_spec(sha="abcdef1234567890")
    calls: list[tuple[object, ...]] = []
    monkeypatch.setattr(
        "sase.ace.tui.actions.hints._files.schedule_copy_delivery",
        lambda owner, value, **kwargs: calls.append((owner, value, kwargs)),
    )

    _handle_commit_attached_target(screen, _target(spec), "copy")  # type: ignore[arg-type]

    assert calls == [
        (
            screen,
            spec.sha,
            {"copied_label": "commit SHA", "task_name": "sase-pager-copy-commit"},
        )
    ]


def test_commit_attached_target_edit_opens_editor_with_diff_path(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    screen = _FakeScreen()
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

    _handle_commit_attached_target(screen, _target(spec), "edit")  # type: ignore[arg-type]

    assert run_calls == [["nvim", str(diff_path)]]


def test_commit_attached_target_edit_without_diff_path_warns() -> None:
    screen = _FakeScreen()
    spec = _commit_spec()

    _handle_commit_attached_target(screen, _target(spec), "edit")  # type: ignore[arg-type]

    screen.notify.assert_called_once()
    assert "No raw diff path" in screen.notify.call_args.args[0]


def test_commit_attached_target_follow_opens_commit_view_modal() -> None:
    screen = _FakeScreen()
    spec = _commit_spec()

    _handle_commit_attached_target(screen, _target(spec), "follow")  # type: ignore[arg-type]

    screen.app.push_screen.assert_called_once()
    modal = screen.app.push_screen.call_args.args[0]
    assert isinstance(modal, CommitViewModal)
    assert modal._commit_specs == (spec,)
