"""Focused visual snapshots for the unintegrated provider creation form."""

from __future__ import annotations

import pytest
from textual.app import ComposeResult
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Static

from sase.ace.testing import AcePage
from sase.ace.tui.widgets.repo_creation_form import RepoCreationFormWidget
from sase.workspace_provider._hookspec import (
    RepoCreationChoice,
    RepoCreationField,
    RepoCreationForm,
)
from tests.ace.tui.visual._ace_png_snapshot_helpers import (
    patches,
    patch_startup_loaders,
    wait_for_startup,
    wait_for_visual_idle,
)
from tests.ace.tui.visual.png_diff import AcePngSnapshotFixture

pytestmark = pytest.mark.visual


def _form() -> RepoCreationForm:
    return RepoCreationForm(
        workflow_type="gh",
        namespace="sase-org",
        can_create=True,
        fields=(
            RepoCreationField(
                name="visibility",
                label="Visibility",
                kind="choice",
                default="private",
                choices=(
                    RepoCreationChoice(value="public", label="Public"),
                    RepoCreationChoice(value="private", label="Private"),
                    RepoCreationChoice(
                        value="internal",
                        label="Internal",
                        disabled_reason="Requires an enterprise plan.",
                    ),
                ),
            ),
            RepoCreationField(
                name="readme",
                label="Add README",
                kind="bool",
                default="true",
            ),
            RepoCreationField(
                name="license",
                label="License",
                kind="search",
                default="MIT",
                choices=(
                    RepoCreationChoice(value="MIT"),
                    RepoCreationChoice(value="Apache-2.0"),
                ),
            ),
            RepoCreationField(
                name="template",
                label="Template repository",
                kind="line",
                group="advanced",
                excludes=("readme", "license"),
            ),
            RepoCreationField(
                name="include_all_branches",
                label="Include all branches",
                kind="bool",
                group="advanced",
                requires=("template",),
            ),
        ),
    )


class _FormPreviewScreen(ModalScreen[None]):
    DEFAULT_CSS = """
    _FormPreviewScreen {
        align: center middle;
    }
    #repo-creation-form-preview {
        width: 96%;
        height: 88%;
        border: round $accent;
        background: $surface;
        padding: 0 1;
    }
    #repo-creation-form-preview-title {
        height: 2;
        text-style: bold;
        color: $secondary;
        content-align: center middle;
    }
    """

    def __init__(self, values: dict[str, str] | None = None) -> None:
        super().__init__()
        self._values = values

    def compose(self) -> ComposeResult:
        with Vertical(id="repo-creation-form-preview"):
            yield Static(
                "Provider options · GitHub / sase-org",
                id="repo-creation-form-preview-title",
            )
            yield RepoCreationFormWidget(_form(), self._values)


async def _open_preview(page: AcePage, values: dict[str, str] | None = None):
    await wait_for_startup(page)
    screen = _FormPreviewScreen(values)
    page.app.push_screen(screen)
    await page.expect_modal("_FormPreviewScreen")
    await wait_for_visual_idle(page)
    return screen.query_one(RepoCreationFormWidget)


async def test_repo_creation_form_basics_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_startup_loaders(monkeypatch)
    async with AcePage(query='"visual"', patches=patches()) as page:
        form = await _open_preview(page)
        assert not form.query_one("#repo-creation-form-field-3").display
        await wait_for_visual_idle(page)
        ace_png_visual.assert_page_png(
            page,
            "repo_creation_form_basics_120x40",
            title="Repository creation form basics",
        )


async def test_repo_creation_form_advanced_exclusions_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_startup_loaders(monkeypatch)
    async with AcePage(query='"visual"', patches=patches()) as page:
        form = await _open_preview(page, {"template": "sase-org/starter"})
        form.query_one("#repo-creation-form-advanced-toggle", Button).press()
        await wait_for_visual_idle(page)
        assert form.query_one("#repo-creation-form-value-1").disabled
        assert form.query_one("#repo-creation-form-value-2").disabled
        ace_png_visual.assert_page_png(
            page,
            "repo_creation_form_advanced_exclusions_120x40",
            title="Repository creation form advanced exclusions",
        )
