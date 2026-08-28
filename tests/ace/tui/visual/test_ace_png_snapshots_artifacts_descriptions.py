"""ACE PNG visual coverage for Artifacts pane descriptions."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from sase.ace.testing import AcePage
from sase.ace.testing import _startup as ace_startup
from sase.ace.tui import artifact_tabs
from sase.ace.tui._artifact_tab_descriptors import (
    assign_artifacts_digit_shortcuts,
    fixed_descriptor,
    provider_descriptors,
)
from sase.ace.tui._artifact_tab_model import (
    ProjectProviderRecord,
    ProviderLoadResult,
)
from sase.ace.tui.widgets.artifacts.beads_pane import ArtifactsBeadsPane
from sase.ace.tui.widgets.artifacts.plans_data import PlansSnapshot
from sase.ace.tui.widgets.artifacts.plans_pane import ArtifactsDocumentsPane
from sase.sidecar_ref_config import SidecarRefPolicy
from tests.ace.tui._artifacts_beads_helpers import snapshot as _beads_snapshot
from tests.ace.tui._artifacts_plans_helpers import _choices, _snapshot as _plan_snapshot
from tests.ace.tui.visual._ace_agents_png_snapshot_helpers import (
    assert_page_svg_contains,
)
from tests.ace.tui.visual._ace_png_snapshot_helpers import (
    patches,
    patch_startup_loaders,
    wait_for_startup,
    wait_for_svg_contains,
    wait_for_visual_idle,
)
from tests.ace.tui.visual.png_diff import AcePngSnapshotFixture

pytestmark = pytest.mark.visual


@pytest.mark.parametrize(
    ("mode", "snapshot_name"),
    (
        ("off", "artifacts_description_off_120x40"),
        ("summary", "artifacts_description_summary_120x40"),
        ("full", "artifacts_description_full_120x40"),
    ),
)
async def test_artifacts_description_modes_png_snapshot(
    mode: str,
    snapshot_name: str,
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    patch_startup_loaders(monkeypatch)
    snapshot = _beads_snapshot(tmp_path)
    monkeypatch.setattr(
        "sase.ace.tui.actions.artifacts._collect_artifacts_project_choices",
        _choices,
    )
    monkeypatch.setattr(
        "sase.ace.tui.widgets.artifacts.beads_pane.load_beads_snapshot",
        lambda _project, **_kwargs: snapshot,
    )

    async with AcePage(query='"visual"', patches=patches()) as page:
        await wait_for_startup(page)
        await page.press(page.artifacts_digit("beads"))
        await page.expect_state("artifacts_subtab", "beads")
        page.app.artifacts_description_mode = mode
        pane = page.query_one_widget("#artifacts-beads-pane", ArtifactsBeadsPane)
        await page.wait_for(lambda _state: pane.snapshot is snapshot)
        await page.wait_for(
            lambda _state: getattr(pane, "_project_display_name", None) == "Alpha",
            timeout=15.0,
        )
        await wait_for_svg_contains(page, "Ready for triage")
        await wait_for_visual_idle(page)

        if mode == "off":
            assert "The work SASE tracks" not in page.export_svg(
                title="Artifacts description off assertion"
            )
        else:
            assert_page_svg_contains(page, "The work SASE tracks")
        if mode == "full":
            assert_page_svg_contains(page, "Rows come from")
            assert_page_svg_contains(page, "bead store")

        ace_png_visual.assert_page_png(
            page,
            snapshot_name,
            title=f"ACE Artifacts - Description {mode}",
        )


async def test_unconfigured_provider_description_hint_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    patch_startup_loaders(monkeypatch)
    _install_notes_provider(monkeypatch, tmp_path)
    snapshot = _empty_notes_snapshot(tmp_path)
    monkeypatch.setattr(
        "sase.ace.tui.actions.artifacts._collect_artifacts_project_choices",
        _choices,
    )
    monkeypatch.setattr(
        "sase.ace.tui.widgets.artifacts.plans_pane.load_plans_snapshot",
        lambda _project, **_kwargs: snapshot,
    )

    artifact_tabs.reset_artifacts_subtabs_cache()
    try:
        async with AcePage(query='"visual"', patches=patches()) as page:
            await wait_for_startup(page)
            await page.press(page.artifacts_digit("ref:notes"))
            await page.expect_state("artifacts_subtab", "ref:notes")
            page.app.artifacts_description_mode = "full"
            pane = page.query_one_widget(
                "#artifacts-ref-notes-pane",
                ArtifactsDocumentsPane,
            )
            await page.wait_for(lambda _state: pane.snapshot is snapshot)
            await wait_for_svg_contains(page, "No notes documents")
            await wait_for_visual_idle(page)

            assert_page_svg_contains(page, "Notes documents contributed")
            assert_page_svg_contains(page, "sidecar repos.")
            assert_page_svg_contains(page, "Describe this pane with")
            assert_page_svg_contains(page, "ref:notes")

            ace_png_visual.assert_page_png(
                page,
                "artifacts_description_unconfigured_provider_hint_120x40",
                title="ACE Artifacts - Unconfigured provider description hint",
            )
    finally:
        artifact_tabs.reset_artifacts_subtabs_cache()


def _install_notes_provider(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    spec: dict[str, Any] = {
        "schema_version": 1,
        "provider": "notes",
        "ref": {
            "kind": "notes",
            "icon": "¶",
            "inventory": {"globs": ["**/*.md"]},
            "identity": {},
            "publication": {},
        },
    }
    record = ProjectProviderRecord(
        project="alpha",
        display_name="Alpha",
        workspace_dir=str(tmp_path / "workspace"),
        role="notes",
        root=tmp_path,
        policy=SidecarRefPolicy(
            role="notes",
            ref_kind="notes",
            is_document=True,
            provider_id="notes",
            spec=spec,
            digest="visual-notes",
        ),
    )
    monkeypatch.setattr(artifact_tabs, "provider_source_token", lambda: ("notes",))
    monkeypatch.setattr(
        artifact_tabs,
        "load_project_provider_records",
        lambda *, project: ProviderLoadResult(records=(record,), issues=()),
    )

    def _fast_artifacts_subtabs() -> tuple[Any, ...]:
        notes_descriptor = provider_descriptors((record,))[0]
        return assign_artifacts_digit_shortcuts(
            (
                fixed_descriptor("agents"),
                fixed_descriptor("stitches"),
                fixed_descriptor("patches"),
                fixed_descriptor("beads"),
                notes_descriptor,
                fixed_descriptor("files"),
            )
        )

    monkeypatch.setattr(ace_startup, "_fast_artifacts_subtabs", _fast_artifacts_subtabs)


def _empty_notes_snapshot(tmp_path: Path) -> PlansSnapshot:
    return replace(
        _plan_snapshot(tmp_path),
        proposals=(),
        active=(),
        archive=(),
        provider_kind="notes",
        provider_label="Notes",
        provider_presentation_digest="visual-notes",
        source_key=("visual-notes",),
    )
