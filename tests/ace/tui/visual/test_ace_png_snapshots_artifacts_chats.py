"""ACE PNG visual snapshot coverage for Artifacts -> Chats."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from sase.ace.testing import AcePage
from sase.ace.tui.widgets.artifacts import chats_pane
from sase.ace.tui.widgets.artifacts.chats_pane import ArtifactsChatsPane
from sase.ace.tui.widgets.artifacts.chats_rendering import CHAT_PROVENANCE_COLORS
from sase.history.chat_catalog_provenance import ChatCatalogSnapshot
from tests.ace.tui._artifacts_chats_helpers import catalog, chat_entry
from tests.ace.tui._artifacts_plans_helpers import _choices
from tests.ace.tui.visual._ace_agents_png_snapshot_helpers import (
    assert_page_svg_contains,
)
from tests.ace.tui.visual._ace_png_snapshot_helpers import (
    changespecs,
    patch_startup_loaders,
    wait_for_startup,
    wait_for_svg_contains,
    wait_for_visual_idle,
)
from tests.ace.tui.visual.png_diff import AcePngSnapshotFixture

pytestmark = pytest.mark.visual


def _chat_fixture_catalog(tmp_path: Path) -> ChatCatalogSnapshot:
    def path_for(name: str) -> str:
        path = tmp_path / f"{name}.md"
        path.write_text(
            f"# {name}\n\nPrompt and response body for {name}.\n",
            encoding="utf-8",
        )
        return str(path)

    return catalog(
        (
            replace(
                chat_entry(
                    "shared-release",
                    provenance="shared",
                    mtime="2026-07-24T16:05:00-04:00",
                ),
                absolute_path=path_for("shared-release"),
                prompt_snippet="Publish the Artifacts Chats rollout note",
            ),
            replace(
                chat_entry(
                    "local-draft",
                    provenance="local",
                    mtime="2026-07-24T15:42:00-04:00",
                ),
                absolute_path=path_for("local-draft"),
                prompt_snippet="Draft local-only follow-up work",
            ),
            replace(
                chat_entry(
                    "remote-zeus",
                    provenance="remote",
                    machine="zeus",
                    mtime="2026-07-24T14:25:00-04:00",
                ),
                absolute_path=path_for("remote-zeus"),
                prompt_snippet="Review imported history from Zeus",
            ),
            replace(
                chat_entry(
                    "remote-hermes",
                    provenance="remote",
                    machine="hermes",
                    mtime="2026-07-24T13:10:00-04:00",
                ),
                absolute_path=path_for("remote-hermes"),
                prompt_snippet="Compare remote sidecar state from Hermes",
            ),
            replace(
                chat_entry(
                    "unknown-sidecar",
                    provenance="unknown",
                    mtime="2026-07-24T12:05:00-04:00",
                ),
                absolute_path=path_for("unknown-sidecar"),
                agent_artifact_dir=None,
                prompt_snippet="Diagnose missing sidecar provenance",
            ),
        )
    )


async def test_artifacts_chats_populated_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    patch_startup_loaders(monkeypatch)
    catalog_snapshot = _chat_fixture_catalog(tmp_path)
    monkeypatch.setattr(
        "sase.ace.tui.actions.artifacts._collect_artifacts_project_choices",
        _choices,
    )
    monkeypatch.setattr(
        chats_pane,
        "load_chat_catalog",
        lambda **_kwargs: catalog_snapshot,
    )

    async with AcePage(query='"visual"', changespecs=changespecs()) as page:
        await wait_for_startup(page)
        await page.press("5")
        await page.expect_state("artifacts_subtab", "chats")
        pane = page.query_one_widget("#artifacts-chats-pane", ArtifactsChatsPane)
        await page.wait_for(
            lambda _state: (
                pane.snapshot is not None
                and pane.snapshot.entries == catalog_snapshot.entries
            )
        )
        await wait_for_svg_contains(page, "shared-release")
        await wait_for_svg_contains(page, "From this machine")
        await wait_for_visual_idle(page)

        for token in ("◇ local", "◆ shared", "⇣ zeus", "⇣ hermes", "◌ ?"):
            assert_page_svg_contains(page, token)
        svg = page.export_svg(title="ACE Artifacts Chats populated assertion")
        assert svg.count("▌") >= len(catalog_snapshot.entries)
        for color in CHAT_PROVENANCE_COLORS.values():
            assert color.casefold() in svg.casefold()

        ace_png_visual.assert_page_png(
            page,
            "artifacts_chats_populated_120x40",
            title="ACE Artifacts - Chats populated",
        )
