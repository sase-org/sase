"""PNG snapshot for the snippet trigger-name panel's collision verdict."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from sase.ace.testing import AcePage
from sase.ace.tui.modals.snippet_name_modal import SnippetNameModal
from sase.xprompt.snippet_targets import SnippetConfigLocation, SnippetSaveTarget
from tests.ace.tui.visual._ace_png_snapshot_helpers import (
    patches,
    patch_startup_loaders,
    wait_for_startup,
    wait_for_svg_contains,
    wait_for_visual_idle,
)
from tests.ace.tui.visual.png_diff import AcePngSnapshotFixture

pytestmark = pytest.mark.visual


def _write_snippets(path: Path, snippets: dict[str, str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump({"ace": {"snippets": snippets}}), encoding="utf-8")


def _location(path: Path, display: str) -> SnippetConfigLocation:
    return SnippetConfigLocation(
        label=path.name,
        path=str(path),
        display_path=display,
        disabled_reason=None,
    )


def _target(path: Path, display: str) -> SnippetSaveTarget:
    return SnippetSaveTarget(
        read_path=path,
        write_path=path,
        apply_target=None,
        via_chezmoi=False,
        display_path=display,
        source="configured",
        fallback_reason=None,
    )


async def test_snippet_name_collision_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    patch_startup_loaders(monkeypatch)
    dest = tmp_path / "dest.yml"
    other = tmp_path / "other.yml"
    _write_snippets(dest, {})
    _write_snippets(other, {"todo": "- [ ] follow up"})

    modal = SnippetNameModal(
        _target(dest, "~/.config/sase/sase.yml"),
        [
            _location(dest, "~/.config/sase/sase.yml"),
            _location(other, "~/sase/xprompts/todo_helpers.md"),
        ],
        initial_trigger="todo",
    )

    async with AcePage(query='"visual"', patches=patches()) as page:
        await wait_for_startup(page)
        await page.press("4")
        await page.expect_state("artifacts_subtab", "prs")
        page.app.push_screen(modal)
        await page.expect_modal("SnippetNameModal")
        await wait_for_svg_contains(page, "will shadow it")
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            "snippet_name_collision_120x40",
            title="ACE snippet trigger name — collision verdict",
        )
