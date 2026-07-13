"""Functional tests for the recursive finder modal + Ctrl+R prompt wiring."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from _pytest.monkeypatch import MonkeyPatch
from textual.app import App, ComposeResult
from textual.widgets import Static

from sase.ace.tui.modals.recursive_finder_modal import RecursiveFileFinderModal
from sase.ace.tui.widgets.file_completion import CompletionCandidate
from sase.ace.tui.widgets.prompt_text_area import PromptTextArea
from tests._workspace_provider_helpers import patch_git_metadata

from ._completion_helpers import CompletionTestApp


def _candidate(display: str, is_dir: bool = False) -> CompletionCandidate:
    return CompletionCandidate(
        display=display,
        insertion=display,
        is_dir=is_dir,
        name=display.rstrip("/").rsplit("/", 1)[-1],
    )


class _FinderHarness(App[None]):
    """Minimal app that pushes the finder modal and records its result."""

    # Mirror AceApp so ctrl+p reaches the modal instead of the command palette.
    ENABLE_COMMAND_PALETTE = False

    def __init__(
        self,
        candidates: list[CompletionCandidate],
        *,
        initial_query: str = "",
    ) -> None:
        super().__init__()
        self._candidates = candidates
        self._initial_query = initial_query
        self.result: object = "UNSET"

    def compose(self) -> ComposeResult:
        yield Static("")

    def on_mount(self) -> None:
        def _store(result: CompletionCandidate | None) -> None:
            self.result = result

        self.push_screen(
            RecursiveFileFinderModal(
                "./",
                self._candidates,
                initial_query=self._initial_query,
            ),
            _store,
        )


def _sample_candidates() -> list[CompletionCandidate]:
    # Equal-length display paths so the empty-query default ordering (shortest,
    # then lexicographic) matches this listed order, keeping index-based
    # navigation assertions intuitive.
    return [
        _candidate("src/alpha.py"),
        _candidate("src/bravo.py"),
        _candidate("src/delta.py"),
    ]


class TestModalInteraction:
    async def test_type_filters_results(self) -> None:
        harness = _FinderHarness(_sample_candidates())
        async with harness.run_test() as pilot:
            await pilot.pause()
            modal = harness.screen
            assert isinstance(modal, RecursiveFileFinderModal)
            for ch in "bravo":
                await pilot.press(ch)
            assert modal._model.query == "bravo"
            assert modal._model.match_count == 1
            assert modal._model.selected is not None
            assert modal._model.selected.display == "src/bravo.py"

    async def test_backspace_and_ctrl_u_edit_query(self) -> None:
        harness = _FinderHarness(_sample_candidates())
        async with harness.run_test() as pilot:
            await pilot.pause()
            modal = harness.screen
            assert isinstance(modal, RecursiveFileFinderModal)
            for ch in "bravo":
                await pilot.press(ch)
            await pilot.press("backspace")
            assert modal._model.query == "brav"
            await pilot.press("ctrl+u")
            assert modal._model.query == ""
            assert modal._model.match_count == 3

    async def test_ctrl_n_ctrl_p_navigation_wraps(self) -> None:
        harness = _FinderHarness(_sample_candidates())
        async with harness.run_test() as pilot:
            await pilot.pause()
            modal = harness.screen
            assert isinstance(modal, RecursiveFileFinderModal)
            assert modal._model.index == 0
            await pilot.press("ctrl+p")
            assert modal._model.index == 2
            await pilot.press("ctrl+n")
            assert modal._model.index == 0
            await pilot.press("down")
            assert modal._model.index == 1

    async def test_enter_returns_selected_candidate(self) -> None:
        harness = _FinderHarness(_sample_candidates())
        async with harness.run_test() as pilot:
            await pilot.pause()
            await pilot.press("ctrl+n")  # move to src/bravo.py (index 1)
            await pilot.press("enter")
            await pilot.pause()
        assert isinstance(harness.result, CompletionCandidate)
        assert harness.result.display == "src/bravo.py"

    async def test_escape_cancels_with_no_result(self) -> None:
        harness = _FinderHarness(_sample_candidates())
        async with harness.run_test() as pilot:
            await pilot.pause()
            await pilot.press("escape")
            await pilot.pause()
        assert harness.result is None

    async def test_initial_query_preseeds_filter(self) -> None:
        harness = _FinderHarness(_sample_candidates(), initial_query="delta")
        async with harness.run_test() as pilot:
            await pilot.pause()
            modal = harness.screen
            assert isinstance(modal, RecursiveFileFinderModal)
            assert modal._model.query == "delta"
            assert modal._model.match_count == 1
            assert modal._model.selected is not None
            assert modal._model.selected.display == "src/delta.py"


class TestCtrlRPromptWiring:
    async def test_ctrl_r_opens_finder_and_inserts_at_cursor(
        self,
        tmp_path: Path,
        monkeypatch: MonkeyPatch,
    ) -> None:
        monkeypatch.chdir(tmp_path)
        (tmp_path / "src" / "sase" / "ace").mkdir(parents=True)
        (tmp_path / "src" / "sase" / "ace" / "file_completion.py").write_text(
            "x", encoding="utf-8"
        )
        (tmp_path / "src" / "sase" / "foo.py").write_text("x", encoding="utf-8")

        app = CompletionTestApp()
        async with app.run_test() as pilot:
            ta = app.query_one(PromptTextArea)
            ta.load_text("src/")
            ta.cursor_location = (0, 4)
            with patch.object(
                type(ta), "_ace_app", new_callable=lambda: property(lambda _s: app)
            ):
                await pilot.press("ctrl+r")
                await pilot.pause()
                modal = app.screen
                assert isinstance(modal, RecursiveFileFinderModal)
                for ch in "filecomp":
                    await pilot.press(ch)
                selected = modal._model.selected
                assert selected is not None
                assert selected.insertion == "src/sase/ace/file_completion.py"
                await pilot.press("enter")
                await pilot.pause()
            assert ta.text == "src/sase/ace/file_completion.py"

    async def test_ctrl_r_preseeds_partial_filename(
        self,
        tmp_path: Path,
        monkeypatch: MonkeyPatch,
    ) -> None:
        monkeypatch.chdir(tmp_path)
        (tmp_path / "src").mkdir()
        (tmp_path / "src" / "alpha.py").write_text("x", encoding="utf-8")
        (tmp_path / "src" / "beta.py").write_text("x", encoding="utf-8")

        app = CompletionTestApp()
        async with app.run_test() as pilot:
            ta = app.query_one(PromptTextArea)
            ta.load_text("src/alp")
            ta.cursor_location = (0, 7)
            with patch.object(
                type(ta), "_ace_app", new_callable=lambda: property(lambda _s: app)
            ):
                await pilot.press("ctrl+r")
                await pilot.pause()
                modal = app.screen
                assert isinstance(modal, RecursiveFileFinderModal)
                # Partial filename "alp" pre-seeds the fuzzy query.
                assert modal._model.query == "alp"
                assert modal._model.selected is not None
                assert modal._model.selected.insertion == "src/alpha.py"

    async def test_ctrl_r_escape_leaves_prompt_unchanged(
        self,
        tmp_path: Path,
        monkeypatch: MonkeyPatch,
    ) -> None:
        monkeypatch.chdir(tmp_path)
        (tmp_path / "src").mkdir()
        (tmp_path / "src" / "alpha.py").write_text("x", encoding="utf-8")

        app = CompletionTestApp()
        async with app.run_test() as pilot:
            ta = app.query_one(PromptTextArea)
            ta.load_text("src/")
            ta.cursor_location = (0, 4)
            with patch.object(
                type(ta), "_ace_app", new_callable=lambda: property(lambda _s: app)
            ):
                await pilot.press("ctrl+r")
                await pilot.pause()
                assert isinstance(app.screen, RecursiveFileFinderModal)
                await pilot.press("escape")
                await pilot.pause()
            assert ta.text == "src/"

    async def test_ctrl_r_while_ctrl_t_open_uses_selected_dir_as_root(
        self,
        tmp_path: Path,
        monkeypatch: MonkeyPatch,
    ) -> None:
        monkeypatch.chdir(tmp_path)
        (tmp_path / "alpha" / "deep").mkdir(parents=True)
        (tmp_path / "alpha" / "deep" / "target.py").write_text("x", encoding="utf-8")
        (tmp_path / "beta").mkdir()
        (tmp_path / "beta" / "other.py").write_text("x", encoding="utf-8")

        app = CompletionTestApp()
        async with app.run_test() as pilot:
            ta = app.query_one(PromptTextArea)
            ta.load_text("./")
            ta.cursor_location = (0, 2)
            with patch.object(
                type(ta), "_ace_app", new_callable=lambda: property(lambda _s: app)
            ):
                await pilot.press("ctrl+t")
                assert ta._file_completion_active is True
                selected = ta._file_completion_candidates[ta._file_completion_index]
                assert selected.name == "alpha"
                await pilot.press("ctrl+r")
                await pilot.pause()
                modal = app.screen
                assert isinstance(modal, RecursiveFileFinderModal)
                displays = [c.display for c, _ in modal._model.matches]
                # Root derived from the selected "alpha/" entry, so results are
                # scoped under alpha/ and exclude beta/.
                assert any(d.endswith("deep/target.py") for d in displays)
                assert all("beta/" not in d for d in displays)

    async def test_ctrl_r_context_uses_known_project_workspace(
        self,
        tmp_path: Path,
        monkeypatch: MonkeyPatch,
    ) -> None:
        patch_git_metadata(monkeypatch)
        project_root = tmp_path / "bob-cli"
        other_cwd = tmp_path / "cwd"
        (project_root / "sdd").mkdir(parents=True)
        (other_cwd / "sdd").mkdir(parents=True)
        monkeypatch.chdir(other_cwd)
        monkeypatch.setattr(
            "sase.xprompt.loader.get_known_project_workspaces",
            lambda include_states=("enabled",): {"bob-cli": project_root},
        )

        app = CompletionTestApp()
        async with app.run_test():
            ta = app.query_one(PromptTextArea)
            text = "#gh:bob-cli sdd/alp"
            ta.load_text(text)
            ta.cursor_location = (0, len(text))

            ctx = ta._compute_recursive_finder_context()

        assert ctx is not None
        assert ctx.root_display == "sdd/"
        assert ctx.root_abs == str(project_root / "sdd")
        assert ctx.query == "alp"
