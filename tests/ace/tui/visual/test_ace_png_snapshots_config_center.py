"""ACE TUI PNG visual snapshots for the SASE Config modal.

Covers both internal tabs and the Phase 4 Config-tab states. The Config tab is
fed a deterministic fixture inventory by patching
``config_pane._load_config_view`` so no real config files are read; the four
required states are exercised:

- **populated** — source rail, schema field tree (with modified markers and
  winning-layer badges), and the provenance detail pane.
- **empty** — a schema with no fields shows the empty placeholder.
- **loading** — the worker is suppressed so the loading placeholder is shown.
- **long-value** — a field with a very long effective value, selected so the
  detail pane shows it wrapping.

XPrompts are injected deterministically by patching ``get_all_prompts`` /
``get_all_project_local_prompts`` / ``classify_source`` in the pane module.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import patch

import pytest
from textual.widgets import Input

from sase.ace.testing import AcePage
from sase.ace.tui.modals import config_pane as cp
from sase.ace.tui.modals import plugins_browser_pane as pbp
from sase.ace.tui.modals.config_center_modal import CenterTab, ConfigCenterModal
from sase.ace.tui.modals.config_edit_modal import ConfigEditModal
from sase.ace.tui.modals.config_pane import ConfigPane
from sase.ace.tui.modals.plugins_browser_pane import PluginsBrowserPane
from sase.config.core import ConfigLayer
from sase.config.inventory import build_config_inventory, config_field_model
from sase.xprompt.models import InputArg, InputType
from sase.xprompt.workflow_models import Workflow, WorkflowStep
from tests.ace.tui.test_plugins_browser_pane import (
    _NOW as _PLUGINS_NOW,
    _catalog,
    _entry,
    _highlight,
    _not_uv_tool,
    _ready_preview,
    _update_ready,
)
from tests.ace.tui.visual._ace_png_snapshot_helpers import (
    changespecs,
    patch_startup_loaders,
    wait_for_startup,
    wait_for_visual_idle,
)
from tests.ace.tui.visual.png_diff import AcePngSnapshotFixture

pytestmark = pytest.mark.visual

BROAD_SCREENSHOT_MAX_DIFF_RATIO = 0.03

_LONG_QUERY = (
    "status:running and (agent:planner or agent:coder) and "
    "project:visual_demo and not tag:archived and updated_after:2026-01-01"
)


# --- Deterministic config fixtures ----------------------------------------


def _config_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "timezone": {
                "type": "string",
                "default": "America/New_York",
                "description": "IANA timezone used for all dates.",
            },
            "use_chezmoi": {
                "type": "boolean",
                "default": False,
                "description": "Manage home-dir config via chezmoi.",
            },
            "axe": {
                "type": "object",
                "additionalProperties": False,
                "description": "Background AXE engine settings.",
                "properties": {
                    "max_hook_runners": {
                        "type": "integer",
                        "default": 3,
                        "description": "Max concurrent hook runners.",
                    },
                    "query": {
                        "type": "string",
                        "default": "",
                        "description": "Default AXE query filter.",
                    },
                    "chop_script_dirs": {
                        "type": "array",
                        "items": {"type": "string"},
                        "default": [],
                        "description": "Directories scanned for chop scripts.",
                    },
                },
            },
            "linked_repos": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {"name": {"type": "string"}},
                },
                "default": [],
                "description": "Linked sibling repositories.",
            },
            "sibling_repos": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {"name": {"type": "string"}},
                },
                "description": "Deprecated alias for linked_repos.",
            },
        },
    }


def _config_layers(*, long_value: bool = False) -> list[ConfigLayer]:
    user_axe: dict[str, Any] = {"max_hook_runners": 5}
    if long_value:
        user_axe["query"] = _LONG_QUERY
    return [
        ConfigLayer(
            name="default",
            path=None,
            exists=True,
            list_strategy="concatenate",
            data={
                "timezone": "America/New_York",
                "use_chezmoi": False,
                "axe": {
                    "max_hook_runners": 3,
                    "query": "",
                    "chop_script_dirs": ["builtin"],
                },
                "linked_repos": [{"name": "core"}],
            },
        ),
        ConfigLayer(
            name="user",
            path="/home/visual/.config/sase/sase.yml",
            exists=True,
            list_strategy="replace",
            data={
                "timezone": "US/Pacific",
                "axe": user_axe,
                "sibling_repos": [{"name": "legacy"}],
            },
        ),
        ConfigLayer(
            name="overlay:sase_work.yml",
            path="/home/visual/.config/sase/sase_work.yml",
            exists=True,
            list_strategy="concatenate",
            data={"axe": {"chop_script_dirs": ["work"]}},
        ),
        ConfigLayer(
            name="overlay:missing.yml",
            path="/home/visual/.config/sase/missing.yml",
            exists=False,
            list_strategy="concatenate",
            data={},
        ),
    ]


def _build_view(schema: dict[str, Any], layers: list[ConfigLayer]) -> cp.ConfigPaneView:
    with patch(
        "sase.config.inventory.load_config_layers",
        return_value=layers,
    ):
        inventory = build_config_inventory(schema=schema)
    field_model = config_field_model(schema)
    return cp.ConfigPaneView.build(field_model, inventory)


def _patch_config_view(
    monkeypatch: pytest.MonkeyPatch, view: cp.ConfigPaneView | None
) -> None:
    result = cp._LoadResult(view=view, error=None, token=("visual", 1))
    monkeypatch.setattr(cp, "_load_config_view", lambda **_kw: result)


# --- XPrompt fixtures ------------------------------------------------------


def _xprompts() -> dict[str, Workflow]:
    return {
        "review": Workflow(
            name="review",
            description="Review a selected diff for correctness.",
            inputs=[
                InputArg(
                    name="diff",
                    type=InputType.PATH,
                    description="Diff file to inspect.",
                )
            ],
            steps=[WorkflowStep(name="prompt", prompt_part="Review {{ diff }}.")],
            source_path="/home/visual/.xprompts/review.md",
        ),
        "ship": Workflow(
            name="ship",
            description="Ship the current change end-to-end.",
            steps=[WorkflowStep(name="run", agent="ship the change")],
            source_path="/home/visual/.xprompts/ship.yml",
        ),
    }


def _patch_xprompt_sources(monkeypatch: pytest.MonkeyPatch) -> None:
    prompts = _xprompts()
    monkeypatch.setattr(
        "sase.ace.tui.modals.xprompt_browser_pane.get_all_prompts",
        lambda project=None: dict(prompts),
    )
    monkeypatch.setattr(
        "sase.xprompt.loader.get_all_project_local_prompts",
        lambda: {},
    )
    monkeypatch.setattr(
        "sase.ace.tui.modals.xprompt_browser_pane.classify_source",
        lambda source_path: (
            "Home ~/.xprompts/",
            source_path.replace("/home/visual", "~"),
            True,
        ),
    )


# --- Plugins fixtures ------------------------------------------------------


def _patch_plugins_catalog(
    monkeypatch: pytest.MonkeyPatch,
    *,
    catalog: Any | None = "default",
    error: str | None = None,
) -> None:
    """Stub the Plugins pane's catalog load with a deterministic result."""
    resolved = _catalog() if catalog == "default" else catalog
    result = pbp._PluginsLoadResult(catalog=resolved, error=error, now=_PLUGINS_NOW)
    monkeypatch.setattr(pbp, "_load_plugins_catalog", lambda **_kw: result)


@pytest.fixture(autouse=True)
def _stub_plugins_loader(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep the (now always-mounted) Plugins pane off the network everywhere.

    The pane is composed in every Config Center screenshot even when its tab
    is hidden, so its worker would otherwise shell out to ``gh``. Tests that
    snapshot the Plugins tab itself override this with their own catalog.
    """
    _patch_plugins_catalog(monkeypatch)


# --- Modal helpers ---------------------------------------------------------


async def _open_modal(page: AcePage, initial_tab: CenterTab) -> ConfigCenterModal:
    modal = ConfigCenterModal(initial_tab=initial_tab)
    page.app.push_screen(modal)
    await page.expect_modal("ConfigCenterModal")
    await wait_for_visual_idle(page)
    return modal


async def _open_config_modal(page: AcePage) -> tuple[ConfigCenterModal, ConfigPane]:
    modal = ConfigCenterModal(initial_tab="config")
    page.app.push_screen(modal)
    await page.expect_modal("ConfigCenterModal")
    await page.wait_for(lambda _s: bool(modal.query("#config")))
    pane = modal.query_one("#config", ConfigPane)
    await page.wait_for(lambda _s: bool(pane._node_by_path))
    await wait_for_visual_idle(page)
    return modal, pane


async def _open_plugins_modal(
    page: AcePage,
) -> tuple[ConfigCenterModal, PluginsBrowserPane]:
    modal = ConfigCenterModal(initial_tab="plugins")
    page.app.push_screen(modal)
    await page.expect_modal("ConfigCenterModal")
    await page.wait_for(lambda _s: bool(modal.query("#plugins")))
    pane = modal.query_one("#plugins", PluginsBrowserPane)
    await page.wait_for(lambda _s: not pane._loading)
    await wait_for_visual_idle(page)
    return modal, pane


async def _wait_for_plugins_detail(page: AcePage, pane: PluginsBrowserPane) -> None:
    """Let the pane's debounced detail repaint settle before snapshotting.

    The Plugins pane owns its own :class:`DetailPanelDebouncer` (not one of the
    app-level debouncers ``wait_for_visual_idle`` tracks), so wait for it to
    drain explicitly, then flush layout/paints.
    """
    debouncer = pane._detail_debouncer
    if debouncer is not None:
        await page.wait_for(lambda _s: not debouncer.is_pending)
    await wait_for_visual_idle(page)


# --- Snapshots -------------------------------------------------------------


async def test_config_center_config_tab_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_startup_loaders(monkeypatch)
    _patch_xprompt_sources(monkeypatch)
    _patch_config_view(monkeypatch, _build_view(_config_schema(), _config_layers()))

    async with AcePage(query='"visual"', changespecs=changespecs()) as page:
        await wait_for_startup(page)
        await _open_config_modal(page)

        ace_png_visual.assert_page_png(
            page,
            "config_center_config_tab_120x40",
            title="ACE SASE Config — Settings tab (populated)",
            max_diff_ratio=BROAD_SCREENSHOT_MAX_DIFF_RATIO,
        )


async def test_config_center_config_empty_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_startup_loaders(monkeypatch)
    _patch_xprompt_sources(monkeypatch)
    empty_schema = {"type": "object", "additionalProperties": False, "properties": {}}
    _patch_config_view(monkeypatch, _build_view(empty_schema, _config_layers()))

    async with AcePage(query='"visual"', changespecs=changespecs()) as page:
        await wait_for_startup(page)
        modal = ConfigCenterModal(initial_tab="config")
        page.app.push_screen(modal)
        await page.expect_modal("ConfigCenterModal")
        await page.wait_for(lambda _s: bool(modal.query("#config")))
        pane = modal.query_one("#config", ConfigPane)
        await page.wait_for(lambda _s: pane._view is not None and not pane._loading)
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            "config_center_config_empty_120x40",
            title="ACE SASE Config — Settings tab (no fields)",
            max_diff_ratio=BROAD_SCREENSHOT_MAX_DIFF_RATIO,
        )


async def test_config_center_config_loading_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_startup_loaders(monkeypatch)
    _patch_xprompt_sources(monkeypatch)
    # Suppress the worker so the pane stays in its initial loading state.
    monkeypatch.setattr(ConfigPane, "_start_load", lambda self, *, force=False: None)

    async with AcePage(query='"visual"', changespecs=changespecs()) as page:
        await wait_for_startup(page)
        await _open_modal(page, "config")

        ace_png_visual.assert_page_png(
            page,
            "config_center_config_loading_120x40",
            title="ACE SASE Config — Settings tab (loading)",
            max_diff_ratio=BROAD_SCREENSHOT_MAX_DIFF_RATIO,
        )


async def test_config_center_config_long_value_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_startup_loaders(monkeypatch)
    _patch_xprompt_sources(monkeypatch)
    view = _build_view(_config_schema(), _config_layers(long_value=True))
    _patch_config_view(monkeypatch, view)

    async with AcePage(query='"visual"', changespecs=changespecs()) as page:
        await wait_for_startup(page)
        _, pane = await _open_config_modal(page)
        # Select the field whose effective value is a long query string.
        pane._do_jump("axe.query")
        await page.wait_for(lambda _s: pane._selected_path == "axe.query")
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            "config_center_config_long_value_120x40",
            title="ACE SASE Config — Settings tab (long value)",
            max_diff_ratio=BROAD_SCREENSHOT_MAX_DIFF_RATIO,
        )


async def test_config_center_xprompts_tab_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_startup_loaders(monkeypatch)
    _patch_xprompt_sources(monkeypatch)
    _patch_config_view(monkeypatch, _build_view(_config_schema(), _config_layers()))

    async with AcePage(query='"visual"', changespecs=changespecs()) as page:
        await wait_for_startup(page)
        await _open_modal(page, "xprompts")

        ace_png_visual.assert_page_png(
            page,
            "config_center_xprompts_tab_120x40",
            title="ACE SASE Config — XPrompts tab (migrated browser)",
            max_diff_ratio=BROAD_SCREENSHOT_MAX_DIFF_RATIO,
        )


# --- Phase 2: Plugins tab list states -------------------------------------


async def test_config_center_plugins_tab_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Populated list + the built-in plugin's ``show``-equivalent detail panel."""
    patch_startup_loaders(monkeypatch)
    _patch_xprompt_sources(monkeypatch)
    _patch_config_view(monkeypatch, _build_view(_config_schema(), _config_layers()))
    _patch_plugins_catalog(monkeypatch)

    async with AcePage(query='"visual"', changespecs=changespecs()) as page:
        await wait_for_startup(page)
        _, pane = await _open_plugins_modal(page)
        await page.wait_for(lambda _s: pane._detail_name == "github")
        await _wait_for_plugins_detail(page, pane)

        ace_png_visual.assert_page_png(
            page,
            "config_center_plugins_tab_120x40",
            title="ACE SASE Config — Plugins tab (list + built-in detail)",
            max_diff_ratio=BROAD_SCREENSHOT_MAX_DIFF_RATIO,
        )


async def test_config_center_plugins_community_detail_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A highlighted community plugin leads its detail with the warning panel."""
    patch_startup_loaders(monkeypatch)
    _patch_xprompt_sources(monkeypatch)
    _patch_config_view(monkeypatch, _build_view(_config_schema(), _config_layers()))
    _patch_plugins_catalog(monkeypatch)

    async with AcePage(query='"visual"', changespecs=changespecs()) as page:
        await wait_for_startup(page)
        _, pane = await _open_plugins_modal(page)
        # Walk down to the lone community plugin (acme).
        pane.action_next_option()
        pane.action_next_option()
        pane.action_next_option()
        await page.wait_for(lambda _s: pane._detail_name == "acme")
        await _wait_for_plugins_detail(page, pane)

        ace_png_visual.assert_page_png(
            page,
            "config_center_plugins_community_detail_120x40",
            title="ACE SASE Config — Plugins tab (community warning + detail)",
            max_diff_ratio=BROAD_SCREENSHOT_MAX_DIFF_RATIO,
        )


async def test_config_center_plugins_long_description_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A long plugin description wraps cleanly in the detail panel."""
    patch_startup_loaders(monkeypatch)
    _patch_xprompt_sources(monkeypatch)
    _patch_config_view(monkeypatch, _build_view(_config_schema(), _config_layers()))
    from sase.plugins.catalog import PluginCatalog
    from sase.plugins.installed import InstalledInfo
    from sase.plugins.latest import LatestInfo

    long_description = (
        "A comprehensive integration that synchronizes issues, pull requests, "
        "CI status, deployment events, and release notes across multiple forges, "
        "then mirrors them into SASE ChangeSpecs with configurable field "
        "mappings, automatic retries, and rate-limit-aware exponential backoff."
    )
    megasync = _entry(
        "megasync",
        owner="sase-org",
        description=long_description,
        installed=InstalledInfo(installed=True, version="1.0.0"),
        latest=LatestInfo(checked=True, version="1.0.0", source="index"),
        topics=("sase-plugin", "sync", "integration"),
    )
    catalog = PluginCatalog(
        fetched_at=_PLUGINS_NOW,
        entries=(megasync,),
        from_cache=True,
        stale=False,
    )
    _patch_plugins_catalog(monkeypatch, catalog=catalog)

    async with AcePage(query='"visual"', changespecs=changespecs()) as page:
        await wait_for_startup(page)
        _, pane = await _open_plugins_modal(page)
        await page.wait_for(lambda _s: pane._detail_name == "megasync")
        await _wait_for_plugins_detail(page, pane)

        ace_png_visual.assert_page_png(
            page,
            "config_center_plugins_long_description_120x40",
            title="ACE SASE Config — Plugins tab (long description wraps)",
            max_diff_ratio=BROAD_SCREENSHOT_MAX_DIFF_RATIO,
        )


async def test_config_center_plugins_offline_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Offline toggle surfaces the header OFFLINE badge; detail still renders."""
    patch_startup_loaders(monkeypatch)
    _patch_xprompt_sources(monkeypatch)
    _patch_config_view(monkeypatch, _build_view(_config_schema(), _config_layers()))
    _patch_plugins_catalog(monkeypatch)

    async with AcePage(query='"visual"', changespecs=changespecs()) as page:
        await wait_for_startup(page)
        _, pane = await _open_plugins_modal(page)
        pane.action_toggle_offline()
        await page.wait_for(lambda _s: pane._offline and not pane._loading)
        await page.wait_for(lambda _s: pane._detail_name == "github")
        await _wait_for_plugins_detail(page, pane)

        ace_png_visual.assert_page_png(
            page,
            "config_center_plugins_offline_120x40",
            title="ACE SASE Config — Plugins tab (offline badge)",
            max_diff_ratio=BROAD_SCREENSHOT_MAX_DIFF_RATIO,
        )


async def test_config_center_plugins_verbose_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verbose toggle adds the stars / updated columns to the list rows."""
    patch_startup_loaders(monkeypatch)
    _patch_xprompt_sources(monkeypatch)
    _patch_config_view(monkeypatch, _build_view(_config_schema(), _config_layers()))
    _patch_plugins_catalog(monkeypatch)

    async with AcePage(query='"visual"', changespecs=changespecs()) as page:
        await wait_for_startup(page)
        _, pane = await _open_plugins_modal(page)
        pane.action_toggle_verbose()
        await page.wait_for(
            lambda _s: any(
                "★" in pane._row_text(entry).plain
                for _, _, entries in pane._grouped
                for entry in entries
            )
        )
        await _wait_for_plugins_detail(page, pane)

        ace_png_visual.assert_page_png(
            page,
            "config_center_plugins_verbose_120x40",
            title="ACE SASE Config — Plugins tab (verbose rows)",
            max_diff_ratio=BROAD_SCREENSHOT_MAX_DIFF_RATIO,
        )


async def test_config_center_plugins_empty_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Empty catalog shows the no-plugins placeholder."""
    patch_startup_loaders(monkeypatch)
    _patch_xprompt_sources(monkeypatch)
    _patch_config_view(monkeypatch, _build_view(_config_schema(), _config_layers()))
    from sase.plugins.catalog import PluginCatalog

    empty = PluginCatalog(
        fetched_at=_PLUGINS_NOW, entries=(), from_cache=True, stale=False
    )
    _patch_plugins_catalog(monkeypatch, catalog=empty)

    async with AcePage(query='"visual"', changespecs=changespecs()) as page:
        await wait_for_startup(page)
        await _open_plugins_modal(page)

        ace_png_visual.assert_page_png(
            page,
            "config_center_plugins_empty_120x40",
            title="ACE SASE Config — Plugins tab (empty catalog)",
            max_diff_ratio=BROAD_SCREENSHOT_MAX_DIFF_RATIO,
        )


async def test_config_center_plugins_loading_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Suppressing the worker keeps the pane in its initial loading state."""
    patch_startup_loaders(monkeypatch)
    _patch_xprompt_sources(monkeypatch)
    _patch_config_view(monkeypatch, _build_view(_config_schema(), _config_layers()))
    monkeypatch.setattr(
        PluginsBrowserPane, "_start_load", lambda self, *, force=False: None
    )

    async with AcePage(query='"visual"', changespecs=changespecs()) as page:
        await wait_for_startup(page)
        await _open_modal(page, "plugins")

        ace_png_visual.assert_page_png(
            page,
            "config_center_plugins_loading_120x40",
            title="ACE SASE Config — Plugins tab (loading)",
            max_diff_ratio=BROAD_SCREENSHOT_MAX_DIFF_RATIO,
        )


# --- Phase 4: install preview modal + not-uv-tool state --------------------


async def test_config_center_plugins_install_preview_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The install confirm-preview modal: exact uv argv + source toggle."""
    patch_startup_loaders(monkeypatch)
    _patch_xprompt_sources(monkeypatch)
    _patch_config_view(monkeypatch, _build_view(_config_schema(), _config_layers()))
    _patch_plugins_catalog(monkeypatch)
    monkeypatch.setattr(
        pbp, "_plan_install_preview", lambda name, *, offline: _ready_preview(name)
    )

    async with AcePage(query='"visual"', changespecs=changespecs()) as page:
        await wait_for_startup(page)
        _, pane = await _open_plugins_modal(page)
        _highlight(pane, "nvim")  # a not-installed plugin
        await page.wait_for(lambda _s: pane._highlighted_name() == "nvim")
        pane.action_install()
        await page.expect_modal("PluginActionConfirmModal")
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            "config_center_plugins_install_preview_120x40",
            title="ACE SASE Config — Plugins install (confirm preview)",
            max_diff_ratio=BROAD_SCREENSHOT_MAX_DIFF_RATIO,
        )


async def test_config_center_plugins_not_uv_tool_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A non-uv-tool install surfaces the unavailable banner; no ``i install``."""
    patch_startup_loaders(monkeypatch)
    _patch_xprompt_sources(monkeypatch)
    _patch_config_view(monkeypatch, _build_view(_config_schema(), _config_layers()))
    result = pbp._PluginsLoadResult(
        catalog=_catalog(), error=None, now=_PLUGINS_NOW, uv_tool=_not_uv_tool()
    )
    monkeypatch.setattr(pbp, "_load_plugins_catalog", lambda **_kw: result)

    async with AcePage(query='"visual"', changespecs=changespecs()) as page:
        await wait_for_startup(page)
        _, pane = await _open_plugins_modal(page)
        await page.wait_for(lambda _s: pane._detail_name == "github")
        await _wait_for_plugins_detail(page, pane)

        ace_png_visual.assert_page_png(
            page,
            "config_center_plugins_not_uv_tool_120x40",
            title="ACE SASE Config — Plugins tab (install unavailable)",
            max_diff_ratio=BROAD_SCREENSHOT_MAX_DIFF_RATIO,
        )


# --- Phase 5: update preview modals (single + all) ------------------------


async def test_config_center_plugins_update_preview_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The single-plugin update confirm-preview modal: exact uv upgrade argv."""
    patch_startup_loaders(monkeypatch)
    _patch_xprompt_sources(monkeypatch)
    _patch_config_view(monkeypatch, _build_view(_config_schema(), _config_layers()))
    _patch_plugins_catalog(monkeypatch)
    plan = _update_ready(("github",))
    monkeypatch.setattr(
        pbp,
        "_plan_update_preview",
        lambda query, *, all_plugins, offline: pbp._UpdatePreview(plan=plan),
    )

    async with AcePage(query='"visual"', changespecs=changespecs()) as page:
        await wait_for_startup(page)
        _, pane = await _open_plugins_modal(page)
        _highlight(pane, "github")  # installed + update available
        await page.wait_for(lambda _s: pane._highlighted_name() == "github")
        pane.action_update()
        await page.expect_modal("PluginActionConfirmModal")
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            "config_center_plugins_update_preview_120x40",
            title="ACE SASE Config — Plugins update (confirm preview)",
            max_diff_ratio=BROAD_SCREENSHOT_MAX_DIFF_RATIO,
        )


async def test_config_center_plugins_update_all_preview_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The update-all confirm-preview modal: upgrades every installed plugin."""
    patch_startup_loaders(monkeypatch)
    _patch_xprompt_sources(monkeypatch)
    _patch_config_view(monkeypatch, _build_view(_config_schema(), _config_layers()))
    _patch_plugins_catalog(monkeypatch)
    plan = _update_ready(("github", "telegram"), all_plugins=True)
    monkeypatch.setattr(
        pbp,
        "_plan_update_preview",
        lambda query, *, all_plugins, offline: pbp._UpdatePreview(plan=plan),
    )

    async with AcePage(query='"visual"', changespecs=changespecs()) as page:
        await wait_for_startup(page)
        _, pane = await _open_plugins_modal(page)
        pane.action_update_all()
        await page.expect_modal("PluginActionConfirmModal")
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            "config_center_plugins_update_all_preview_120x40",
            title="ACE SASE Config — Plugins update-all (confirm preview)",
            max_diff_ratio=BROAD_SCREENSHOT_MAX_DIFF_RATIO,
        )


# --- Phase 5: edit modal states -------------------------------------------


async def _open_edit_modal(page: AcePage, path: str) -> ConfigEditModal:
    """Open the Config edit modal for the leaf at *path*."""
    _, pane = await _open_config_modal(page)
    pane._do_jump(path)
    await page.wait_for(lambda _s: pane._selected_path == path)
    pane.action_edit_field()
    await page.expect_modal("ConfigEditModal")
    modal = page.app.screen
    assert isinstance(modal, ConfigEditModal)
    await page.wait_for(lambda _s: bool(modal.query("#config-edit-scope")))
    return modal


async def test_config_center_edit_modal_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The edit stage: scope selector + typed editor for a string field."""
    patch_startup_loaders(monkeypatch)
    _patch_xprompt_sources(monkeypatch)
    monkeypatch.setattr("sase.config.edit.get_use_chezmoi", lambda: False)
    _patch_config_view(monkeypatch, _build_view(_config_schema(), _config_layers()))

    async with AcePage(query='"visual"', changespecs=changespecs()) as page:
        await wait_for_startup(page)
        await _open_edit_modal(page, "timezone")
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            "config_center_edit_modal_120x40",
            title="ACE SASE Config — edit field (scope + editor)",
            max_diff_ratio=BROAD_SCREENSHOT_MAX_DIFF_RATIO,
        )


async def test_config_center_edit_preview_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The preview stage: target file, effective merge, validation, and diff."""
    patch_startup_loaders(monkeypatch)
    _patch_xprompt_sources(monkeypatch)
    monkeypatch.setattr("sase.config.edit.get_use_chezmoi", lambda: False)
    _patch_config_view(monkeypatch, _build_view(_config_schema(), _config_layers()))

    async with AcePage(query='"visual"', changespecs=changespecs()) as page:
        await wait_for_startup(page)
        modal = await _open_edit_modal(page, "timezone")
        modal.query_one("#config-edit-input", Input).value = "UTC"
        modal.action_confirm()  # plan -> preview
        await page.wait_for(lambda _s: modal._plan is not None)
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            "config_center_edit_preview_120x40",
            title="ACE SASE Config — edit preview (diff + validation)",
            max_diff_ratio=BROAD_SCREENSHOT_MAX_DIFF_RATIO,
        )
