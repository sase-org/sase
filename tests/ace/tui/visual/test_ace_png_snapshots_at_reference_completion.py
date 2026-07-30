"""ACE PNG snapshot for the grouped ``@`` reference completion menu."""

from __future__ import annotations

from pathlib import Path

import pytest

from sase.ace.testing import AcePage
from sase.ace.tui.widgets.artifact_ref_completion import (
    ARTIFACT_REF_COMPLETION_KIND,
    AtReferenceFileCompletionMetadata,
    ArtifactRefKindCompletionMetadata,
)
from sase.ace.tui.widgets.file_completion import CompletionCandidate
from sase.ace.tui.widgets.prompt_path_inventory import load_prompt_path_snapshot
from tests.ace.tui.visual._ace_png_snapshot_helpers import (
    changespecs,
    patch_startup_loaders,
    wait_for_startup,
    wait_for_svg_contains,
    wait_for_visual_idle,
)
from tests.ace.tui.visual._ace_prompt_png_snapshot_helpers import mount_prompt_bar
from tests.ace.tui.visual.png_diff import AcePngSnapshotFixture

pytestmark = pytest.mark.visual


def _artifact_kind(
    name: str,
    *,
    builtin: bool,
    detail: str,
) -> CompletionCandidate:
    return CompletionCandidate(
        display=name,
        insertion=f"@{name}:",
        is_dir=False,
        name=name,
        metadata=ArtifactRefKindCompletionMetadata(name, builtin, detail),
    )


def _workspace_rows(workspace: Path) -> list[CompletionCandidate]:
    snapshot = load_prompt_path_snapshot(str(workspace))
    return [
        CompletionCandidate(
            display=f"{row.name}/" if row.is_dir else row.name,
            insertion=f"@{row.name}/" if row.is_dir else f"@{row.name}",
            is_dir=row.is_dir,
            name=row.name,
            metadata=AtReferenceFileCompletionMetadata(row.is_dir, ""),
        )
        for row in snapshot.rows
    ]


async def test_at_reference_completion_panel_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    patch_startup_loaders(monkeypatch)
    workspace = tmp_path / "reference-menu"
    (workspace / "docs").mkdir(parents=True)
    (workspace / "src").mkdir()
    (workspace / "Justfile").write_text("test:\n\tjust check\n", encoding="utf-8")
    (workspace / "README.md").write_text("# Reference menu\n", encoding="utf-8")
    rows = [
        _artifact_kind("commit", builtin=True, detail="builtin"),
        _artifact_kind(
            "plans",
            builtin=False,
            detail="document · ~/plans",
        ),
        *_workspace_rows(workspace),
    ]

    async with AcePage(query='"visual"', changespecs=changespecs()) as page:
        await wait_for_startup(page)
        await page.press("5")
        await page.expect_state("artifacts_subtab", "prs")
        await page.expect_state("tab", "changespecs")
        bar = await mount_prompt_bar(page, "Attach a project reference")
        bar.show_file_completions(
            "artifact kinds",
            rows,
            selected_index=1,
            completion_kind=ARTIFACT_REF_COMPLETION_KIND,
            group_rule=True,
            group_directory="~/reference-menu",
        )
        await wait_for_svg_contains(page, "files · ~/reference-menu")
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            "at_reference_completion_panel_120x40",
            title="ACE prompt input — grouped @ reference completion",
        )
