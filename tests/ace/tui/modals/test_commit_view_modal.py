"""Tests for the commit view modal."""

from __future__ import annotations

from pathlib import Path
from threading import Event

from textual.app import App, ComposeResult
from textual.widgets import Static

from sase.ace.tui.modals.commit_view_modal import CommitViewModal
from sase.ace.tui.widgets.prompt_panel._agent_display_state import CommitViewSpec


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

    title = CommitViewModal([spec])._build_title().plain

    assert "gh:pallets/click (external)" in title


async def _wait_for_diff(
    pilot,
    modal: CommitViewModal,
    expected_text: str,
) -> None:
    for _ in range(50):
        if (
            modal._diff_loaded
            and modal._diff_text
            and expected_text in modal._diff_text
        ):
            return
        await pilot.pause()
    raise AssertionError(f"commit diff did not load expected text: {expected_text}")


async def test_commit_view_modal_copies_sha_and_closes(
    tmp_path: Path,
    monkeypatch,
) -> None:
    diff_path = tmp_path / "commit.diff"
    _write_diff(diff_path, old="old", new="new")
    copied: list[str] = []
    monkeypatch.setattr(
        "sase.ace.tui.modals.commit_view_modal.copy_to_system_clipboard",
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
        "sase.ace.tui.modals.commit_view_modal.copy_to_system_clipboard",
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

    def fake_load(spec: CommitViewSpec) -> str:
        if spec.sha == first.sha:
            first_started.set()
            release_first.wait(timeout=2)
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
        for _ in range(50):
            if first_started.is_set():
                break
            await pilot.pause()
        assert first_started.is_set()

        await pilot.press("ctrl+n")
        await _wait_for_diff(pilot, modal, "+fresh second")
        release_first.set()
        for _ in range(5):
            await pilot.pause()

        assert modal._current_index == 1
        assert modal._diff_text is not None
        assert "+fresh second" in modal._diff_text
        assert "+stale first" not in modal._diff_text
