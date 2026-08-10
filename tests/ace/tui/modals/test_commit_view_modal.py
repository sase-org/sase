"""Tests for the commit view modal."""

from __future__ import annotations

from dataclasses import replace
from io import StringIO
from pathlib import Path
from threading import Event

import pytest
from rich.console import Console
from rich.text import Text
from textual.app import App, ComposeResult
from textual.containers import VerticalScroll
from textual.widgets import Static

from sase.ace.testing import wait_for
from sase.ace.tui.modals.commit_view_modal import CommitViewModal
from sase.ace.tui.util.lazy_syntax import PLAIN_RENDER_MAX_BYTES
from sase.ace.tui.widgets.prompt_panel._agent_display_state import CommitViewSpec
from sase.plan_documents import PlanDocument


class _CommitModalTestApp(App[None]):
    ENABLE_COMMAND_PALETTE = False

    def __init__(
        self,
        specs: list[CommitViewSpec],
        *,
        initial_index: int = 0,
    ) -> None:
        super().__init__()
        self.specs = specs
        self.initial_index = initial_index

    def compose(self) -> ComposeResult:
        yield Static("host")

    def on_mount(self) -> None:
        self.push_screen(CommitViewModal(self.specs, initial_index=self.initial_index))


def _spec(
    diff_path: str,
    *,
    sha: str = "abcdef1234567890",
    subject: str = "feat: modal",
    message: str = "feat: modal\n\nRender commit details.",
) -> CommitViewSpec:
    return CommitViewSpec(
        short_sha=sha[:12],
        sha=sha,
        repo_name="sase",
        cwd="/workspace/sase",
        subject=subject,
        message=message,
        diff_path=diff_path,
        is_primary=True,
    )


def _write_diff(path: Path, *, old: str, new: str) -> None:
    path.write_text(
        f"""diff --git a/src/example.py b/src/example.py
--- a/src/example.py
+++ b/src/example.py
@@ -1 +1 @@
-{old}
+{new}
""",
        encoding="utf-8",
    )


def _rendered_text(renderable: object) -> str:
    stream = StringIO()
    Console(file=stream, color_system=None, width=120).print(renderable)
    return stream.getvalue()


def test_commit_view_title_labels_external_repo() -> None:
    spec = CommitViewSpec(
        short_sha="abcdef123456",
        sha="abcdef1234567890",
        repo_name="gh:pallets/click",
        cwd="/workspace/sase/repos/external/gh/pallets/click",
        subject="fix: parser",
        message="fix: parser",
        diff_path=None,
        is_primary=False,
        repo_kind="external",
    )

    title = _rendered_text(CommitViewModal([spec])._build_title())

    assert "gh:pallets/click (external)" in title


def test_commit_view_title_shows_time_chip_when_created_at_set(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "sase.ace.tui.modals.commit_view_modal.build_commit_time_chip",
        lambda timestamp, **_kwargs: Text(f"CHIP:{timestamp}"),
    )
    spec = replace(_spec("/missing/commit.diff"), created_at=1_700_000_000)

    title = _rendered_text(CommitViewModal([spec])._build_title())

    assert "CHIP:1700000000" in title


def test_commit_view_modal_marks_merge_and_parents() -> None:
    spec = replace(
        _spec("/missing/commit.diff", sha="mmmmmmm1234567890"),
        parent_ids=("a" * 40, "b" * 40),
    )
    modal = CommitViewModal([spec])
    modal._diff_loaded = True
    modal._diff_text = (
        "diff --git a/src/app.py b/src/app.py\n"
        "--- a/src/app.py\n"
        "+++ b/src/app.py\n"
        "@@ -1 +1 @@\n"
        "-old\n"
        "+new\n"
    )

    title = _rendered_text(modal._build_title())
    content = _rendered_text(modal._build_content())

    assert "mmmmmmm12345  ◆ merge" in title
    assert "Parents    aaaaaaaaaaaa bbbbbbbbbbbb" in content
    assert "Changes introduced by this merge (vs first parent)" in content
    assert "+new" in content


def test_commit_view_title_omits_metadata_row_when_nothing_to_show() -> None:
    spec = CommitViewSpec(
        short_sha="abcdef123456",
        sha="abcdef1234567890",
        repo_name="sase",
        cwd=None,
        subject="chore: bare",
        message="chore: bare",
        diff_path=None,
        is_primary=True,
    )

    title = _rendered_text(CommitViewModal([spec])._build_title())

    assert title.rstrip("\n").count("\n") == 0
    assert "chore: bare" in title


def test_commit_view_title_long_diff_path_ellipsizes_without_clipping_chip(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "sase.ace.tui.modals.commit_view_modal.build_commit_time_chip",
        lambda timestamp, **_kwargs: Text("Today 07:05:54 · 2h ago"),
    )
    spec = replace(
        _spec("/" + ("x" * 300) + "/commit.diff"),
        created_at=1_700_000_000,
    )

    title = _rendered_text(CommitViewModal([spec])._build_title())
    metadata_line = title.splitlines()[1]

    assert "…" in metadata_line
    assert metadata_line.rstrip().endswith("Today 07:05:54 · 2h ago")
    assert len(metadata_line) <= 120


def test_commit_view_content_bounds_byte_heavy_diff_and_explains_truncation() -> None:
    modal = CommitViewModal([_spec("/missing/commit.diff")])
    modal._diff_loaded = True
    modal._diff_text = ("+" + "x" * 7_000 + "\n") * 500

    text = _rendered_text(modal._build_content())

    assert len(text.encode("utf-8")) <= PLAIN_RENDER_MAX_BYTES + 20_000
    assert "approximately" in text
    assert "run git show abcdef123456 in sase" in text


async def _wait_for_diff(
    pilot,
    modal: CommitViewModal,
    expected_text: str,
) -> None:
    try:
        await wait_for(
            pilot,
            lambda: bool(
                modal._diff_loaded
                and modal._diff_text
                and expected_text in modal._diff_text
            ),
        )
    except AssertionError as exc:
        raise AssertionError(
            f"commit diff did not load expected text: {expected_text}"
        ) from exc


async def _wait_for_plan(pilot, modal: CommitViewModal) -> None:
    try:
        await wait_for(
            pilot,
            lambda: bool(
                modal._display_mode == "plan" and modal._plan_document is not None
            ),
        )
    except AssertionError as exc:
        raise AssertionError("commit plan did not load") from exc


async def test_commit_view_modal_copies_sha_and_closes(
    tmp_path: Path,
    monkeypatch,
) -> None:
    diff_path = tmp_path / "commit.diff"
    _write_diff(diff_path, old="old", new="new")
    copied: list[str] = []
    monkeypatch.setattr(
        "sase.ace.tui.actions.clipboard._delivery.copy_to_system_clipboard",
        lambda content: copied.append(content) is None or True,
    )
    app = _CommitModalTestApp([_spec(str(diff_path))])

    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        modal = app.screen_stack[-1]
        assert isinstance(modal, CommitViewModal)

        await _wait_for_diff(pilot, modal, "+new")
        modal.query_one("#commit-view-content", Static)
        assert modal._diff_loaded is True
        assert modal._diff_text is not None
        assert "diff --git" in modal._diff_text

        await pilot.press("y")
        await pilot.pause()
        assert copied == ["abcdef1234567890"]

        await pilot.press("q")
        await pilot.pause()
        assert not isinstance(app.screen_stack[-1], CommitViewModal)


async def test_commit_view_modal_navigates_wrapping_and_copies_current_sha(
    tmp_path: Path,
    monkeypatch,
) -> None:
    first_diff = tmp_path / "first.diff"
    second_diff = tmp_path / "second.diff"
    _write_diff(first_diff, old="old-one", new="new-one")
    _write_diff(second_diff, old="old-two", new="new-two")
    first = _spec(
        str(first_diff),
        sha="111111111111111111111111",
        subject="feat: first",
        message="feat: first\n\nFirst body.",
    )
    second = _spec(
        str(second_diff),
        sha="222222222222222222222222",
        subject="fix: second",
        message="fix: second\n\nSecond body.",
    )
    copied: list[str] = []
    monkeypatch.setattr(
        "sase.ace.tui.actions.clipboard._delivery.copy_to_system_clipboard",
        lambda content: copied.append(content) is None or True,
    )
    app = _CommitModalTestApp([first, second])

    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        modal = app.screen_stack[-1]
        assert isinstance(modal, CommitViewModal)

        await _wait_for_diff(pilot, modal, "+new-one")
        assert modal._current_index == 0

        await pilot.press("ctrl+n")
        await _wait_for_diff(pilot, modal, "+new-two")
        assert modal._current_index == 1
        assert modal._current_spec is second

        await pilot.press("y")
        await pilot.pause()
        assert copied == ["222222222222222222222222"]

        await pilot.press("ctrl+n")
        await pilot.pause()
        assert modal._current_index == 0
        assert modal._diff_loaded is True
        assert modal._diff_text is not None
        assert "+new-one" in modal._diff_text

        await pilot.press("ctrl+p")
        await pilot.pause()
        assert modal._current_index == 1
        assert modal._diff_loaded is True
        assert modal._diff_text is not None
        assert "+new-two" in modal._diff_text


async def test_commit_view_modal_single_commit_navigation_is_noop(
    tmp_path: Path,
) -> None:
    diff_path = tmp_path / "commit.diff"
    _write_diff(diff_path, old="old", new="new")
    app = _CommitModalTestApp([_spec(str(diff_path))])

    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        modal = app.screen_stack[-1]
        assert isinstance(modal, CommitViewModal)

        await _wait_for_diff(pilot, modal, "+new")
        await pilot.press("ctrl+n")
        await pilot.press("ctrl+p")
        await pilot.pause()

        assert modal._current_index == 0
        assert modal._diff_loaded is True
        assert modal._diff_text is not None
        assert "+new" in modal._diff_text


async def test_commit_view_modal_uses_cached_diff_when_returning_to_commit(
    monkeypatch,
) -> None:
    first = _spec(
        "/missing/first.diff",
        sha="111111111111111111111111",
        subject="feat: first",
    )
    second = _spec(
        "/missing/second.diff",
        sha="222222222222222222222222",
        subject="fix: second",
    )
    calls: list[str] = []

    def fake_load(spec: CommitViewSpec) -> str:
        calls.append(spec.sha)
        return f"diff --git a/{spec.short_sha} b/{spec.short_sha}\n+{spec.subject}\n"

    monkeypatch.setattr(
        "sase.ace.tui.modals.commit_view_modal.load_commit_diff_text",
        fake_load,
    )
    app = _CommitModalTestApp([first, second])

    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        modal = app.screen_stack[-1]
        assert isinstance(modal, CommitViewModal)

        await _wait_for_diff(pilot, modal, "+feat: first")
        await pilot.press("ctrl+n")
        await _wait_for_diff(pilot, modal, "+fix: second")
        await pilot.press("ctrl+p")
        await pilot.pause()

        assert modal._current_index == 0
        assert modal._diff_loaded is True
        assert modal._diff_text is not None
        assert "+feat: first" in modal._diff_text
        assert calls == [
            "111111111111111111111111",
            "222222222222222222222222",
        ]


async def test_commit_view_modal_backfills_time_chip_and_refreshes_title(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    diff_path = tmp_path / "commit.diff"
    _write_diff(diff_path, old="old", new="new")
    spec = _spec(str(diff_path))
    assert spec.created_at is None

    monkeypatch.setattr(
        "sase.ace.tui.modals.commit_view_modal.load_commit_created_at",
        lambda spec: 1_700_000_000,
    )
    monkeypatch.setattr(
        "sase.ace.tui.modals.commit_view_modal.build_commit_time_chip",
        lambda timestamp, **_kwargs: Text(f"CHIP:{timestamp}"),
    )
    app = _CommitModalTestApp([spec])

    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        modal = app.screen_stack[-1]
        assert isinstance(modal, CommitViewModal)

        await _wait_for_diff(pilot, modal, "+new")

        title_widget = modal.query_one("#commit-view-title", Static)
        rendered = _rendered_text(title_widget.content)
        assert "CHIP:1700000000" in rendered


async def test_commit_view_modal_time_chip_tracks_selected_commit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    first_diff = tmp_path / "first.diff"
    second_diff = tmp_path / "second.diff"
    _write_diff(first_diff, old="old-one", new="new-one")
    _write_diff(second_diff, old="old-two", new="new-two")
    first = replace(
        _spec(str(first_diff), sha="111111111111111111111111", subject="feat: first"),
        created_at=1_700_000_000,
    )
    second = replace(
        _spec(str(second_diff), sha="222222222222222222222222", subject="fix: second"),
        created_at=1_800_000_000,
    )
    monkeypatch.setattr(
        "sase.ace.tui.modals.commit_view_modal.build_commit_time_chip",
        lambda timestamp, **_kwargs: Text(f"CHIP:{timestamp}"),
    )
    app = _CommitModalTestApp([first, second])

    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        modal = app.screen_stack[-1]
        assert isinstance(modal, CommitViewModal)
        await _wait_for_diff(pilot, modal, "+new-one")

        title_widget = modal.query_one("#commit-view-title", Static)
        assert "CHIP:1700000000" in _rendered_text(title_widget.content)

        await pilot.press("ctrl+n")
        await _wait_for_diff(pilot, modal, "+new-two")
        assert "CHIP:1800000000" in _rendered_text(title_widget.content)

        await pilot.press("ctrl+p")
        await pilot.pause()
        assert "CHIP:1700000000" in _rendered_text(title_widget.content)


async def test_commit_view_modal_ignores_stale_diff_worker_result(
    monkeypatch,
) -> None:
    first = _spec(
        "/missing/first.diff",
        sha="111111111111111111111111",
        subject="feat: first",
    )
    second = _spec(
        "/missing/second.diff",
        sha="222222222222222222222222",
        subject="fix: second",
    )
    first_started = Event()
    release_first = Event()
    first_finished = Event()

    def fake_load(spec: CommitViewSpec) -> str:
        if spec.sha == first.sha:
            first_started.set()
            release_first.wait(timeout=2)
            first_finished.set()
            return "diff --git a/first b/first\n+stale first\n"
        return "diff --git a/second b/second\n+fresh second\n"

    monkeypatch.setattr(
        "sase.ace.tui.modals.commit_view_modal.load_commit_diff_text",
        fake_load,
    )
    app = _CommitModalTestApp([first, second])

    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        modal = app.screen_stack[-1]
        assert isinstance(modal, CommitViewModal)
        await wait_for(pilot, first_started.is_set)
        assert first_started.is_set()

        await pilot.press("ctrl+n")
        await _wait_for_diff(pilot, modal, "+fresh second")
        release_first.set()
        await wait_for(pilot, first_finished.is_set)

        assert modal._current_index == 1
        assert modal._diff_text is not None
        assert "+fresh second" in modal._diff_text
        assert "+stale first" not in modal._diff_text


async def test_commit_view_modal_toggles_plan_and_restores_cached_diff(
    tmp_path: Path,
) -> None:
    diff_path = tmp_path / "commit.diff"
    plan_path = tmp_path / "plan.md"
    _write_diff(diff_path, old="old", new="new")
    plan_path.write_text("# Attached plan\n\n- Do the work.\n", encoding="utf-8")
    spec = _spec(
        str(diff_path),
        message=f"feat: modal\n\nSASE_PLAN={plan_path}",
    )
    app = _CommitModalTestApp([spec])

    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        modal = app.screen_stack[-1]
        assert isinstance(modal, CommitViewModal)
        await _wait_for_diff(pilot, modal, "+new")
        scroll = modal.query_one("#commit-view-scroll", VerticalScroll)
        scroll.scroll_end(animate=False)

        await pilot.press("p")
        await _wait_for_plan(pilot, modal)

        assert _rendered_text(modal._build_title()).startswith("PLAN")
        assert str(plan_path.resolve()) in _rendered_text(modal._build_title())
        assert "p commit" in modal._build_footer()
        assert "Attached plan" in _rendered_text(modal._build_content())
        assert scroll.scroll_y == 0

        await pilot.press("p")
        await pilot.pause()

        assert modal._display_mode == "commit"
        assert _rendered_text(modal._build_title()).startswith("COMMIT")
        assert "p plan" in modal._build_footer()
        assert modal._diff_loaded is True
        assert modal._diff_text is not None and "+new" in modal._diff_text


async def test_commit_view_modal_time_chip_renders_in_plan_mode(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    diff_path = tmp_path / "commit.diff"
    plan_path = tmp_path / "plan.md"
    _write_diff(diff_path, old="old", new="new")
    plan_path.write_text("# Attached plan\n\n- Do the work.\n", encoding="utf-8")
    monkeypatch.setattr(
        "sase.ace.tui.modals.commit_view_modal.build_commit_time_chip",
        lambda timestamp, **_kwargs: Text(f"CHIP:{timestamp}"),
    )
    spec = replace(
        _spec(
            str(diff_path),
            message=f"feat: modal\n\nSASE_PLAN={plan_path}",
        ),
        created_at=1_700_000_000,
    )
    app = _CommitModalTestApp([spec])

    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        modal = app.screen_stack[-1]
        assert isinstance(modal, CommitViewModal)
        await _wait_for_diff(pilot, modal, "+new")

        await pilot.press("p")
        await _wait_for_plan(pilot, modal)

        assert "CHIP:1700000000" in _rendered_text(modal._build_title())


async def test_commit_view_modal_plan_failure_notifies_and_keeps_commit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    diff_path = tmp_path / "commit.diff"
    _write_diff(diff_path, old="old", new="new")
    notices: list[tuple[str, str]] = []

    def notify(
        _self: CommitViewModal,
        message: str,
        *,
        severity: str = "information",
        **_kwargs,
    ) -> None:
        notices.append((message, severity))

    monkeypatch.setattr(CommitViewModal, "notify", notify)
    app = _CommitModalTestApp([_spec(str(diff_path))])

    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        modal = app.screen_stack[-1]
        assert isinstance(modal, CommitViewModal)
        await _wait_for_diff(pilot, modal, "+new")

        await pilot.press("p")
        await wait_for(pilot, lambda: bool(notices))

        assert notices == [("abcdef123456: no SASE_PLAN tag is attached", "warning")]
        assert modal._display_mode == "commit"
        assert modal._diff_text is not None and "+new" in modal._diff_text


async def test_commit_view_modal_toggle_back_ignores_stale_plan_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    started = Event()
    release = Event()
    finished = Event()

    def load_plan(_message: str, **_kwargs) -> PlanDocument:
        started.set()
        release.wait(timeout=2)
        finished.set()
        return PlanDocument(
            "success",
            reference="stale.md",
            path="/plans/stale.md",
            content="# Stale plan\n",
        )

    monkeypatch.setattr(
        "sase.ace.tui.modals.commit_view_modal.load_commit_plan_document",
        load_plan,
    )
    app = _CommitModalTestApp([_spec("/missing/commit.diff")])

    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        modal = app.screen_stack[-1]
        assert isinstance(modal, CommitViewModal)
        await pilot.press("p")
        await wait_for(pilot, started.is_set)
        assert started.is_set()

        await pilot.press("p")
        release.set()
        await wait_for(pilot, finished.is_set)

        assert modal._display_mode == "commit"
        assert "Stale plan" not in _rendered_text(modal._build_content())


async def test_commit_navigation_exits_plan_mode_and_preserves_wrapping(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    first = _spec(
        "/missing/first.diff",
        sha="111111111111111111111111",
        subject="feat: first",
    )
    second = _spec(
        "/missing/second.diff",
        sha="222222222222222222222222",
        subject="fix: second",
    )

    def load_plan(_message: str, **_kwargs) -> PlanDocument:
        return PlanDocument(
            "success",
            reference="plan.md",
            path="/plans/plan.md",
            content="# Plan\n",
        )

    monkeypatch.setattr(
        "sase.ace.tui.modals.commit_view_modal.load_commit_plan_document",
        load_plan,
    )
    app = _CommitModalTestApp([first, second])

    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        modal = app.screen_stack[-1]
        assert isinstance(modal, CommitViewModal)
        await pilot.press("p")
        await _wait_for_plan(pilot, modal)

        await pilot.press("ctrl+p")
        await pilot.pause()

        assert modal._current_index == 1
        assert modal._display_mode == "commit"
        assert modal._current_spec is second
