"""Integration tests for @-prefixed file completion in the prompt widget."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from _pytest.monkeypatch import MonkeyPatch

from sase.ace.testing.wait import wait_for
from sase.ace.tui.widgets.prompt_text_area import PromptTextArea

from ._completion_helpers import CompletionTestApp, create_entries

# Path completion loads its directory inventory on a Textual thread worker
# (``_schedule_prompt_path_inventory_load`` -> ``run_worker(..., thread=True)``),
# so ``pause()`` returns while the listing is still off the message pump. Every
# wait below names the candidate state the worker result produces, which is
# never the state the keypress starts from.


class TestAtPrefixIntegration:
    """Integration tests for @-prefixed file completion in the widget."""

    async def test_at_tilde_triggers_completion(
        self,
        tmp_path: Path,
        monkeypatch: MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("HOME", str(tmp_path))
        create_entries(tmp_path)
        app = CompletionTestApp()
        async with app.run_test() as pilot:
            ta = app.query_one(PromptTextArea)
            ta.load_text("@~/")
            ta.cursor_location = (0, 3)
            with patch.object(
                type(ta), "_ace_app", new_callable=lambda: property(lambda _s: app)
            ):
                assert ta._try_file_completion_tab() is True
            # A pending load shows a single placeholder candidate, so wait for
            # the real home-directory entries rather than for any candidate.
            await wait_for(
                pilot,
                lambda: "alpha" in [c.name for c in ta._file_completion_candidates],
            )
            assert ta._file_completion_active is True
            assert len(ta._file_completion_candidates) > 1
            for c in ta._file_completion_candidates:
                assert c.insertion.startswith("@~/")

    async def test_at_single_match_inserts_with_prefix(
        self,
        tmp_path: Path,
        monkeypatch: MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("HOME", str(tmp_path))
        (tmp_path / "alpha").mkdir()
        app = CompletionTestApp()
        async with app.run_test() as pilot:
            ta = app.query_one(PromptTextArea)
            ta.load_text("@~/al")
            ta.cursor_location = (0, 5)
            with patch.object(
                type(ta), "_ace_app", new_callable=lambda: property(lambda _s: app)
            ):
                assert ta._try_file_completion_tab() is True
            # The insertion lands first and the menu closes only once the
            # worker result confirms the single match, so wait on both.
            await wait_for(
                pilot,
                lambda: ta.text == "@~/alpha/" and not ta._file_completion_active,
            )
            assert ta._file_completion_active is False

    async def test_at_prefix_directory_drilldown(
        self,
        tmp_path: Path,
        monkeypatch: MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("HOME", str(tmp_path))
        (tmp_path / "alpha").mkdir()
        (tmp_path / "beta").mkdir()
        (tmp_path / "alpha" / "foo.py").write_text("x", encoding="utf-8")
        (tmp_path / "alpha" / "bar.py").write_text("x", encoding="utf-8")
        app = CompletionTestApp()
        async with app.run_test() as pilot:
            ta = app.query_one(PromptTextArea)
            ta.load_text("@~/")
            ta.cursor_location = (0, 3)
            with patch.object(
                type(ta), "_ace_app", new_callable=lambda: property(lambda _s: app)
            ):
                await pilot.press("ctrl+t")
                await wait_for(
                    pilot,
                    lambda: "alpha" in [c.name for c in ta._file_completion_candidates],
                )
                assert ta._file_completion_active is True
                # First candidate should be alpha/ (dirs first, alphabetical)
                assert ta._file_completion_candidates[0].name == "alpha"
                # Accept the directory via Ctrl+L to drill down
                await pilot.press("ctrl+l")
                assert ta.text == "@~/alpha/"
                # The drilldown listing is a second worker load, so wait for
                # alpha's entries to replace the home-directory candidates.
                await wait_for(
                    pilot,
                    lambda: (
                        "foo.py" in [c.name for c in ta._file_completion_candidates]
                    ),
                )
                assert ta._file_completion_active is True
                names = [c.name for c in ta._file_completion_candidates]
                assert "foo.py" in names
                assert "bar.py" in names
                for c in ta._file_completion_candidates:
                    assert c.insertion.startswith("@~/alpha/")
