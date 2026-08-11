"""ACE PNG snapshot for the grouped ``@`` reference completion menu."""

from __future__ import annotations

from pathlib import Path

import pytest

from sase.ace.testing import AcePage
from sase.ace.tui.widgets.artifact_ref_completion import (
    ARTIFACT_REF_COMPLETION_KIND,
    AtReferenceFileCompletionMetadata,
    ArtifactRefKindCompletionMetadata,
    ArtifactRefPayloadCompletionMetadata,
)
from sase.ace.tui.widgets.file_completion import CompletionCandidate
from sase.ace.tui.widgets.prompt_path_inventory import load_prompt_path_snapshot
from tests.ace.tui.visual._ace_png_snapshot_helpers import (
    patches,
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


def _document_payload(
    path: str,
    title: str,
    *,
    fuzzy: bool,
) -> CompletionCandidate:
    path_start = path.rfind("site") if fuzzy else -1
    title_start = title.find("Site") if fuzzy else -1
    return CompletionCandidate(
        display=path,
        insertion=f"@research:{path}",
        is_dir=False,
        name=Path(path).name,
        metadata=ArtifactRefPayloadCompletionMetadata(
            kind="research",
            payload=path,
            source="document",
            label=title,
            detail="research",
            age="3d",
            label_match=((path_start, path_start + 4),) if path_start >= 0 else (),
            title_match=((title_start, title_start + 4),) if title_start >= 0 else (),
            match_tier=2 if fuzzy else 0,
        ),
    )


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

    async with AcePage(query='"visual"', patches=patches()) as page:
        await wait_for_startup(page)
        await page.press("2")
        await page.expect_state("artifacts_subtab", "patches")
        await page.expect_state("tab", "patches")
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


async def test_fuzzy_at_reference_payload_panel_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_startup_loaders(monkeypatch)
    rows = [
        _document_payload(
            "202607/sase_sites_hub_and_pages/sase_sites_hub_and_pages.md",
            "SASE Sites Hub and Pages",
            fuzzy=True,
        ),
        _document_payload(
            "202605/site_deployment_checklist.md",
            "Site Deployment Checklist",
            fuzzy=True,
        ),
        _document_payload(
            "202604/research_portal.md",
            "Research Site Portal",
            fuzzy=True,
        ),
    ]

    async with AcePage(query='"visual"', patches=patches()) as page:
        await wait_for_startup(page)
        bar = await mount_prompt_bar(page, "Attach research")
        bar.show_file_completions(
            "research: documents",
            rows,
            selected_index=0,
            completion_kind=ARTIFACT_REF_COMPLETION_KIND,
            artifact_ref_payload_count=3,
            artifact_ref_payload_total=305,
        )
        await wait_for_svg_contains(page, "fuzzy")
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            "at_reference_fuzzy_payload_panel_120x40",
            title="ACE prompt input — fuzzy @ payload completion",
        )


async def test_truncated_at_reference_payload_panel_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_startup_loaders(monkeypatch)
    rows = [
        _document_payload(
            "202607/site_inventory.md",
            "Site Inventory",
            fuzzy=False,
        ),
        _document_payload(
            "202607/site_rollout.md",
            "Site Rollout",
            fuzzy=False,
        ),
    ]

    async with AcePage(query='"visual"', patches=patches()) as page:
        await wait_for_startup(page)
        bar = await mount_prompt_bar(page, "Attach research")
        bar.show_file_completions(
            "research: documents",
            rows,
            selected_index=0,
            completion_kind=ARTIFACT_REF_COMPLETION_KIND,
            artifact_ref_payload_count=2,
            artifact_ref_payload_total=1205,
            artifact_ref_truncated_payloads=1203,
        )
        await wait_for_svg_contains(page, "not scanned")
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            "at_reference_truncated_payload_panel_120x40",
            title="ACE prompt input — truncated @ payload completion",
        )
