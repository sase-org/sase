"""PNG snapshot for the snippet trigger-name panel's collision verdict."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from sase.ace.testing import AcePage
from sase.ace.tui.actions.agent_workflow import (
    _prompt_bar_snippet_location as location_mod,
)
from sase.ace.tui.modals.save_location_choices import snippet_location_choices
from sase.ace.tui.modals.save_location_picker_modal import SaveLocationPickerModal
from sase.ace.tui.modals.snippet_name_modal import SnippetNameModal
from sase.macro.snippet_targets import SnippetConfigLocation, SnippetSaveTarget
from sase.snippet.catalog import _build_snippet_catalog
from sase.snippet.models import (
    SnippetCatalogContext,
    SnippetSourceContribution,
)
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

    catalog = _build_snippet_catalog(
        SnippetCatalogContext(key=None, name=None, aliases=(), workspace_dir=None),
        macro_entries=(),
        config_contributions=(
            SnippetSourceContribution(
                trigger="todo",
                template="- [ ] follow up",
                kind="project",
                path=str(other),
                display_path="~/sase/macros/todo_helpers.md",
                writable=True,
                layer="local",
            ),
        ),
        layer_paths=(str(dest), str(other)),
        layer_names=("user", "local"),
    )
    modal = SnippetNameModal(
        _target(dest, "~/.config/sase/sase.yml"),
        [
            _location(dest, "~/.config/sase/sase.yml"),
            _location(other, "~/sase/macros/todo_helpers.md"),
        ],
        catalog=catalog,
        initial_trigger="todo",
    )

    async with AcePage(query='"visual"', patches=patches()) as page:
        await wait_for_startup(page)
        await page.press(page.artifacts_digit("patches"))
        await page.expect_state("artifacts_subtab", "patches")
        page.app.push_screen(modal)
        await page.expect_modal("SnippetNameModal")
        await wait_for_svg_contains(page, "already exists")
        await wait_for_svg_contains(page, "todo_helpers")
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            "snippet_name_collision_120x40",
            title="ACE snippet trigger name — collision verdict",
        )


async def test_snippet_location_flow_picker_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Picker appearance on the snippet location-first path.

    The choices come from the real ``snippet_location_choices`` builder over
    fixture config files, so the golden covers the flow's data path without
    depending on the host's own snippet files.
    """
    patch_startup_loaders(monkeypatch)
    project = tmp_path / "sase" / "sase.yml"
    user = tmp_path / "user.yml"
    _write_snippets(project, {"todo": "- [ ] follow up"})
    _write_snippets(user, {"todo": "- [ ] follow up", "later": "later body"})
    locations = [
        SnippetConfigLocation(
            label="Project sase/sase.yml",
            path=str(project),
            display_path="./sase/sase.yml",
        ),
        SnippetConfigLocation(
            label="User sase.yml",
            path=str(user),
            display_path="~/.config/sase/sase.yml",
        ),
    ]
    resolved = SnippetSaveTarget(
        read_path=user,
        write_path=user,
        apply_target=None,
        via_chezmoi=False,
        display_path="~/.config/sase/sase.yml",
        source="default",
        fallback_reason=None,
    )
    choices, _default_id = snippet_location_choices(
        locations,
        resolved_target=resolved,
        names_by_path={
            str(project): frozenset({"todo"}),
            str(user): frozenset({"todo", "later"}),
        },
        last_used_path=None,
        current_path=None,
        project="sase",
        trigger="",
    )
    modal = SaveLocationPickerModal(
        "snippet",
        "New snippet · where should it live?",
        choices,
    )

    async with AcePage(query='"visual"', patches=patches()) as page:
        await wait_for_startup(page)
        await page.press(page.artifacts_digit("patches"))
        await page.expect_state("artifacts_subtab", "patches")
        page.app.push_screen(modal)
        await page.expect_modal("SaveLocationPickerModal")
        await wait_for_svg_contains(page, "New snippet")
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            "snippet_location_flow_picker_120x40",
            title="ACE snippet location flow — picker",
        )


async def test_snippet_location_flow_finder_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Picker → finder live-flow on ``gt`` then ``e`` with a seeded catalog."""
    patch_startup_loaders(monkeypatch)
    user = tmp_path / "user.yml"
    project = tmp_path / "sase" / "sase.yml"
    _write_snippets(user, {"todo": "TODO($1): $0"})
    _write_snippets(project, {"todo": "- [ ] follow up"})
    locations = [
        SnippetConfigLocation(
            label="Project sase/sase.yml",
            path=str(project),
            display_path="./sase/sase.yml",
        ),
        SnippetConfigLocation(
            label="User sase.yml",
            path=str(user),
            display_path="~/.config/sase/sase.yml",
        ),
    ]
    target = _target(user, "~/.config/sase/sase.yml")
    catalog = _build_snippet_catalog(
        SnippetCatalogContext(key=None, name="visual", aliases=(), workspace_dir=None),
        macro_entries=(),
        config_contributions=(
            SnippetSourceContribution(
                trigger="todo",
                template="TODO($1): $0",
                kind="user",
                path=str(user),
                display_path="~/.config/sase/sase.yml",
                writable=True,
                layer="user",
            ),
            SnippetSourceContribution(
                trigger="todo",
                template="- [ ] follow up",
                kind="project",
                path=str(project),
                display_path="./sase/sase.yml",
                writable=True,
                layer="local",
            ),
            SnippetSourceContribution(
                trigger="help",
                template="plugin help",
                kind="plugin",
                path=None,
                display_path="plugin sase_help",
                writable=False,
                layer="plugin:sase_help",
            ),
        ),
        layer_paths=(str(user), str(project)),
        layer_names=("user", "local"),
    )
    monkeypatch.setattr(
        location_mod, "_load_snippet_locations", lambda _project: locations
    )
    monkeypatch.setattr(
        location_mod, "_resolve_snippet_target", lambda _configured: target
    )
    monkeypatch.setattr(location_mod, "_load_snippet_catalog", lambda _project: catalog)
    monkeypatch.setattr(location_mod, "_load_snippet_last_used_path", lambda: None)
    monkeypatch.setattr(
        location_mod,
        "_load_snippet_names_by_path",
        lambda _project, _configured: {
            str(user): frozenset({"todo"}),
            str(project): frozenset({"todo"}),
        },
    )

    async with AcePage(query='"visual"', patches=patches()) as page:
        await wait_for_startup(page)
        await mount_prompt_bar(page, "Summarize the risky assumptions.")
        await page.press("escape")
        await page.press("g", "t")
        await page.expect_modal("SaveLocationPickerModal")
        await wait_for_svg_contains(page, "2 snippets")
        await page.press("e")
        await page.expect_modal("ExistingDefinitionFinderModal")
        await wait_for_svg_contains(page, "Edit existing snippet")
        await wait_for_visual_idle(page)
        ace_png_visual.assert_page_png(
            page,
            "snippet_location_flow_finder_120x40",
            title="ACE snippet location flow — existing finder",
        )
