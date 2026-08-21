"""ACE TUI PNG snapshots for the Glossary panel in light and dark themes."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from sase.ace.testing import AcePage
from sase.ace.tui.glossary_panel_catalog import (
    GlossaryProjectRef,
    GlossaryProjectSnapshot,
)
from sase.ace.tui.modals import glossary_pane as glossary_pane_module
from sase.ace.tui.modals.glossary_panel import GlossaryPanel
from sase.ace.tui.modals.glossary_panel_load import GlossaryPanelInitialLoad
from sase.core.glossary_facade import GlossaryCatalog, GlossaryEntry
from sase.xprompt.glossary_catalog import (
    EditorGlossaryCatalog,
    EditorGlossaryProject,
    _GlossaryConfigSignature,
)
from tests.ace.tui.visual._ace_png_snapshot_helpers import (
    patch_startup_loaders,
    patches,
    wait_for_startup,
    wait_for_state,
    wait_for_svg_contains,
    wait_for_visual_idle,
)
from tests.ace.tui.visual.png_diff import AcePngSnapshotFixture

pytestmark = pytest.mark.visual


def _ref(
    key: str, display_name: str, *, has_glossary: bool = True
) -> GlossaryProjectRef:
    return GlossaryProjectRef(
        key=key, display_name=display_name, workspace_dir="", has_glossary=has_glossary
    )


def _entry(
    index: int,
    term: str,
    *,
    definition: str,
    display_aliases: tuple[str, ...] = (),
    config_path: Path,
) -> GlossaryEntry:
    return GlossaryEntry(
        index=index,
        term=term,
        normalized_term=term.casefold(),
        definition=definition,
        configured_aliases=display_aliases,
        display_aliases=display_aliases,
        effective_aliases=(term.casefold(), *display_aliases),
        source={
            "config_path": str(config_path),
            "definition_range": {
                "start": {"line": 18 + index * 7, "character": 4},
                "end": {"line": 18 + index * 7, "character": 68},
            },
        },
    )


class _ScanningCompiledGlossary:
    def __init__(self, entries: tuple[GlossaryEntry, ...]) -> None:
        self._entries = entries

    def scan(self, text: str) -> list[dict[str, Any]]:
        spans: list[tuple[int, dict[str, Any]]] = []
        for entry in self._entries:
            start = 0
            while True:
                found = text.find(entry.term, start)
                if found == -1:
                    break
                end = found + len(entry.term)
                spans.append((found, _span(entry, text[found:end], found, end)))
                start = end
        return [span for _found, span in sorted(spans, key=lambda item: item[0])]


def _span(
    entry: GlossaryEntry, matched_text: str, start: int, end: int
) -> dict[str, Any]:
    return {
        "term": entry.term,
        "entry_index": entry.index,
        "alias_index": 0,
        "alias": entry.term,
        "matched_text": matched_text,
        "byte_start": start,
        "byte_end": end,
        "range": {
            "start": {"line": 0, "character": start},
            "end": {"line": 0, "character": end},
        },
        "segments": [
            {
                "byte_start": start,
                "byte_end": end,
                "range": {
                    "start": {"line": 0, "character": start},
                    "end": {"line": 0, "character": end},
                },
            }
        ],
    }


def _populated_snapshot() -> tuple[GlossaryProjectRef, GlossaryProjectSnapshot]:
    ref = _ref("sase", "sase")
    config_path = Path("/workspace/sase/sase.yml")
    entries = (
        _entry(
            0,
            "Agent Clan",
            definition="A named container for related agents.",
            config_path=config_path,
        ),
        _entry(
            1,
            "Agent Hood",
            definition=(
                "An agent hood is a group of agents that share a name prefix. "
                "See Sase Agent."
            ),
            display_aliases=("hood", "agent neighborhood"),
            config_path=config_path,
        ),
        _entry(
            2,
            "Sase Agent",
            definition=(
                "A lane is the sequential home for one agent family. See Agent Clan."
            ),
            config_path=config_path,
        ),
    )
    catalog = EditorGlossaryCatalog(
        schema_version=1,
        project=EditorGlossaryProject(
            key=ref.key,
            name=ref.display_name,
            aliases=(),
            workspace_dir=Path("/workspace/sase"),
        ),
        config_path=config_path,
        config_signature=_GlossaryConfigSignature(
            path=str(config_path), mtime_ns=1, size=2048
        ),
        catalog=GlossaryCatalog(schema_version=1, entries=entries),
        compiled=_ScanningCompiledGlossary(entries),
    )
    return ref, GlossaryProjectSnapshot(
        project=ref,
        catalog=catalog,
        reverse_references={2: ("Agent Hood",)},
        diagnostics=(),
    )


def _empty_snapshot() -> tuple[GlossaryProjectRef, GlossaryProjectSnapshot]:
    ref = _ref("gh_org__research", "Research", has_glossary=False)
    return ref, GlossaryProjectSnapshot(
        project=ref, catalog=None, reverse_references={}, diagnostics=()
    )


def _install_panel_load(
    monkeypatch: pytest.MonkeyPatch,
    ref: GlossaryProjectRef,
    snapshot: GlossaryProjectSnapshot,
) -> None:
    def fake_initial_load(
        *,
        launch_workspace: str | None = None,
        initial_project_key: str | None = None,
        seed_from_current_project: bool = True,
        session_project_key: str | None = None,
    ) -> GlossaryPanelInitialLoad:
        del launch_workspace, initial_project_key, seed_from_current_project
        del session_project_key
        return GlossaryPanelInitialLoad(ring=(ref,), project_index=0, snapshot=snapshot)

    def fake_project_load(project: GlossaryProjectRef) -> GlossaryProjectSnapshot:
        del project
        return snapshot

    monkeypatch.setattr(
        glossary_pane_module, "load_glossary_panel_initial_state", fake_initial_load
    )
    monkeypatch.setattr(
        glossary_pane_module, "load_glossary_project_snapshot", fake_project_load
    )


def _panel_ready(page: AcePage) -> bool:
    screen = page.app.screen
    return isinstance(screen, GlossaryPanel) and not screen._loading


@pytest.mark.parametrize(
    ("theme", "snapshot_name", "title"),
    [
        (
            "textual-dark",
            "glossary_panel_populated_dark_120x40",
            "ACE glossary panel - populated dark theme",
        ),
        (
            "textual-light",
            "glossary_panel_populated_light_120x40",
            "ACE glossary panel - populated light theme",
        ),
    ],
)
async def test_glossary_panel_populated_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
    theme: str,
    snapshot_name: str,
    title: str,
) -> None:
    patch_startup_loaders(monkeypatch)
    ref, snapshot = _populated_snapshot()
    _install_panel_load(monkeypatch, ref, snapshot)

    async with AcePage(query='"visual"', patches=patches()) as page:
        await wait_for_startup(page)
        page.app.theme = theme
        page.app.push_screen(GlossaryPanel(initial_term="Agent Hood"))
        await page.expect_modal("GlossaryPanel")
        await wait_for_state(page, lambda: _panel_ready(page), description="panel load")
        await page.press(">", "1")
        await wait_for_state(
            page,
            lambda: (
                isinstance(page.app.screen, GlossaryPanel)
                and page.app.screen._current_term == "Sase Agent"
                and page.app.screen._trail == ["Agent Hood"]
            ),
            description="followed SEE ALSO to Sase Agent",
        )
        await wait_for_svg_contains(page, "TRAIL")
        await wait_for_svg_contains(page, "SEE ALSO")
        await wait_for_svg_contains(page, "REFERENCED BY")
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(page, snapshot_name, title=title)


@pytest.mark.parametrize(
    ("theme", "snapshot_name", "title"),
    [
        (
            "textual-dark",
            "glossary_panel_empty_dark_120x40",
            "ACE glossary panel - empty dark theme",
        ),
        (
            "textual-light",
            "glossary_panel_empty_light_120x40",
            "ACE glossary panel - empty light theme",
        ),
    ],
)
async def test_glossary_panel_empty_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
    theme: str,
    snapshot_name: str,
    title: str,
) -> None:
    patch_startup_loaders(monkeypatch)
    ref, snapshot = _empty_snapshot()
    _install_panel_load(monkeypatch, ref, snapshot)

    async with AcePage(query='"visual"', patches=patches()) as page:
        await wait_for_startup(page)
        page.app.theme = theme
        page.app.push_screen(GlossaryPanel())
        await page.expect_modal("GlossaryPanel")
        await wait_for_state(page, lambda: _panel_ready(page), description="panel load")
        await wait_for_svg_contains(page, "No glossary in")
        await wait_for_svg_contains(page, "Research")
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(page, snapshot_name, title=title)
