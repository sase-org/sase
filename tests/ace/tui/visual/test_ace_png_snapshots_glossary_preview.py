"""ACE TUI PNG visual snapshots for the glossary preview card."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from sase.ace.testing import AcePage
from sase.ace.tui.modals.glossary_preview_modal import GlossaryPreviewModal
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
    wait_for_svg_contains,
    wait_for_visual_idle,
)
from tests.ace.tui.visual.png_diff import AcePngSnapshotFixture

pytestmark = pytest.mark.visual


@pytest.mark.parametrize(
    ("theme", "snapshot_name", "title"),
    [
        (
            "textual-dark",
            "glossary_preview_card_full_dark_120x40",
            "ACE glossary preview card - full dark theme",
        ),
        (
            "textual-light",
            "glossary_preview_card_full_light_120x40",
            "ACE glossary preview card - full light theme",
        ),
    ],
)
async def test_glossary_preview_card_full_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
    theme: str,
    snapshot_name: str,
    title: str,
) -> None:
    patch_startup_loaders(monkeypatch)
    catalog = _visual_glossary_catalog(full=True)

    async with AcePage(query='"visual"', patches=patches()) as page:
        await wait_for_startup(page)
        page.app.theme = theme
        page.app.push_screen(
            GlossaryPreviewModal(
                catalog,
                catalog.entries[0],
                matched_text="hood",
            )
        )
        await page.expect_modal("GlossaryPreviewModal")
        await wait_for_svg_contains(page, "SEE ALSO")
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(page, snapshot_name, title=title)


async def test_glossary_preview_card_minimal_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_startup_loaders(monkeypatch)
    catalog = _visual_glossary_catalog(full=False)

    async with AcePage(query='"visual"', patches=patches()) as page:
        await wait_for_startup(page)
        page.app.push_screen(
            GlossaryPreviewModal(
                catalog,
                catalog.entries[0],
                matched_text="Patch",
            )
        )
        await page.expect_modal("GlossaryPreviewModal")
        await wait_for_svg_contains(page, "Matches")
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            "glossary_preview_card_minimal_120x40",
            title="ACE glossary preview card - minimal entry",
        )


def _visual_glossary_catalog(*, full: bool) -> EditorGlossaryCatalog:
    config_path = Path("/workspace/sase/sase.yml")
    if full:
        entries = (
            _entry(
                0,
                "Agent Hood",
                definition=(
                    "An agent hood is a group of agents that share a `<name>.` "
                    "prefix. It points readers toward Sase Agent and Agent Clan "
                    "when naming related work."
                ),
                config_path=config_path,
                display_aliases=("hood", "agent neighborhood"),
                effective_aliases=("agent hood", "hood", "agent neighborhood"),
            ),
            _entry(
                1,
                "Sase Agent",
                definition="A lane is the sequential home for one agent family.",
                config_path=config_path,
            ),
            _entry(
                2,
                "Agent Clan",
                definition="A clan is a named rootless container for agents.",
                config_path=config_path,
            ),
        )
    else:
        entries = (
            _entry(
                0,
                "Patch",
                definition="A Patch is SASE's local unit of change.",
                config_path=config_path,
            ),
        )

    return EditorGlossaryCatalog(
        schema_version=1,
        project=EditorGlossaryProject(
            key="sase",
            name="sase",
            aliases=("sase-org",),
            workspace_dir=Path("/workspace/sase"),
        ),
        config_path=config_path,
        config_signature=_GlossaryConfigSignature(
            path=str(config_path),
            mtime_ns=1,
            size=2048,
        ),
        catalog=GlossaryCatalog(schema_version=1, entries=entries),
        compiled=_VisualCompiledGlossary(entries),
    )


def _entry(
    index: int,
    term: str,
    *,
    definition: str,
    config_path: Path,
    display_aliases: tuple[str, ...] = (),
    effective_aliases: tuple[str, ...] | None = None,
) -> GlossaryEntry:
    return GlossaryEntry(
        index=index,
        term=term,
        normalized_term=term.casefold(),
        definition=definition,
        configured_aliases=display_aliases,
        display_aliases=display_aliases,
        effective_aliases=effective_aliases or (term.casefold(), *display_aliases),
        source={
            "config_path": str(config_path),
            "definition_range": {
                "start": {"line": 18 + index * 7, "character": 4},
                "end": {"line": 18 + index * 7, "character": 68},
            },
        },
    )


class _VisualCompiledGlossary:
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
    entry: GlossaryEntry,
    matched_text: str,
    start: int,
    end: int,
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
