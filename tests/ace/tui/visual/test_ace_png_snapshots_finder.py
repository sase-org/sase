"""ACE TUI PNG visual snapshot coverage for the recursive file finder modal.

ChangeSpecs-tab and footer snapshots live in ``test_ace_png_snapshots``.
Shared fixtures live in ``_ace_png_snapshot_helpers``.
"""

from __future__ import annotations

import pytest

from sase.ace.testing import AcePage
from sase.ace.tui.modals.recursive_finder_modal import RecursiveFileFinderModal
from sase.ace.tui.widgets.file_completion import CompletionCandidate
from tests.ace.tui.visual._ace_png_snapshot_helpers import (
    changespecs,
    patch_startup_loaders,
    wait_for_startup,
    wait_for_visual_idle,
)
from tests.ace.tui.visual.png_diff import AcePngSnapshotFixture

pytestmark = pytest.mark.visual


def _finder_candidate(rel: str, is_dir: bool = False) -> CompletionCandidate:
    display = f"src/sase/ace/tui/widgets/{rel}"
    if is_dir:
        display += "/"
    return CompletionCandidate(
        display=display,
        insertion=display,
        is_dir=is_dir,
        name=rel.rstrip("/").rsplit("/", 1)[-1],
    )


def _finder_candidates() -> list[CompletionCandidate]:
    """Deterministic finder candidates: 22 match "wi", 2 do not (22/24)."""
    widget_files = [
        "file_completion.py",
        "_file_completion.py",
        "prompt_input_bar.py",
        "prompt_text_area.py",
        "recursive_file_finder.py",
        "directive_completion.py",
        "xprompt_completion.py",
        "xprompt_arg_assist.py",
        "keybinding_footer.py",
        "changespec_detail.py",
        "bgcmd_list.py",
        "agent_info_panel.py",
        "prompt_completion.py",
        "line_rendering.py",
        "vim_normal.py",
        "vim_motions.py",
        "snippets.py",
        "soft_completion.py",
        "history_panel.py",
        "tab_bar.py",
    ]
    candidates = [_finder_candidate(name) for name in widget_files]
    candidates.append(_finder_candidate("file_panel", is_dir=True))
    candidates.append(_finder_candidate("query", is_dir=True))
    # Two entries outside widgets/ that do not contain the "wi" subsequence.
    candidates.append(
        CompletionCandidate(
            display="src/sase/core/paths.py",
            insertion="src/sase/core/paths.py",
            is_dir=False,
            name="paths.py",
        )
    )
    candidates.append(
        CompletionCandidate(
            display="src/sase/db.py",
            insertion="src/sase/db.py",
            is_dir=False,
            name="db.py",
        )
    )
    return candidates


async def test_recursive_finder_modal_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_startup_loaders(monkeypatch)

    async with AcePage(query='"visual"', changespecs=changespecs()) as page:
        await wait_for_startup(page)
        await page.press("5")
        await page.expect_state("artifacts_subtab", "prs")
        modal = RecursiveFileFinderModal(
            "src/",
            _finder_candidates(),
            initial_query="wi",
        )
        page.app.push_screen(modal)
        await page.expect_modal("RecursiveFileFinderModal")
        await wait_for_visual_idle(page)
        assert modal._model.match_count == 22
        assert modal._model.total == 24

        ace_png_visual.assert_page_png(
            page,
            "recursive_finder_modal_120x40",
            title="ACE recursive finder modal",
        )
