"""Install action tests for the Plugins pane and action confirm modal."""

from __future__ import annotations

import pytest
from textual.containers import VerticalScroll
from textual.widgets import Static

from sase.ace import update_receipt
from sase.ace.testing import AcePage
from sase.ace.tui.modals import plugins_browser_pane as pbp
from sase.ace.tui.modals.plugin_action_confirm_modal import (
    PluginActionConfirmModal,
    PluginActionConfirmResult,
    PluginActionVariant,
)
from sase.plugins.operations import (
    InstallManyOutcome,
    InstallManyReady,
    InstallNotFound,
    InstallOutcome,
    InstallReady,
)
from sase.updates.incoming_commits import (
    CommitSummary,
    IncomingCommits,
    RepoIncomingCommits,
)
from sase.uv_tool.runner import ChangeKind, UvChangeSet, UvPackageChange
from tests.ace.tui._plugins_browser_pane_helpers import (
    _catalog,
    _highlight,
    _not_uv_tool,
    _open_plugins_pane,
    _patch_catalog,
    _patch_catalog_recording,
    _patch_other_panes,
    _ready_many_plan,
    _ready_preview,
    _render,
    _spy_notify,
)


async def test_plugins_pane_install_opens_preview_modal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_other_panes(monkeypatch)
    _patch_catalog(monkeypatch, catalog=_catalog())
    monkeypatch.setattr(
        pbp, "_plan_install_preview", lambda name, *, offline: _ready_preview(name)
    )
    async with AcePage() as page:
        pane = await _open_plugins_pane(page)
        _highlight(pane, "nvim")
        await page.wait_for(lambda _s: pane._highlighted_name() == "nvim")
        pane.action_install()
        await page.expect_modal("PluginActionConfirmModal")
        modal = page.app.screen
        assert isinstance(modal, PluginActionConfirmModal)
        # Both source variants are offered; index is the default (first).
        assert [v.key for v in modal._variants] == ["index", "git"]
        preview = _render(modal._preview_renderable())
        assert "uv tool install" in preview
        assert "Installs nvim" in preview
        assert "from index" in preview


async def test_plugins_pane_install_hint_only_for_not_installed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_other_panes(monkeypatch)
    _patch_catalog(monkeypatch, catalog=_catalog())
    async with AcePage() as page:
        pane = await _open_plugins_pane(page)
        _highlight(pane, "nvim")
        await page.wait_for(lambda _s: pane._highlighted_name() == "nvim")
        assert "i install" in pane._hints()
        _highlight(pane, "github")  # already installed
        await page.wait_for(lambda _s: pane._highlighted_name() == "github")
        assert "i install" not in pane._hints()


async def test_plugins_pane_toggle_install_mark_updates_row_and_hints(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_other_panes(monkeypatch)
    _patch_catalog(monkeypatch, catalog=_catalog())
    async with AcePage() as page:
        pane = await _open_plugins_pane(page)
        _highlight(pane, "nvim")
        await page.wait_for(lambda _s: pane._highlighted_name() == "nvim")

        pane.action_toggle_install_mark()
        await page.wait_for(lambda _s: pane._highlighted_name() == "acme")

        assert pane._marked_install == {"nvim"}
        assert "i install (1)" in pane._hints()
        assert "1 marked" in pane._hints()
        assert "esc clear" in pane._hints()
        option_list = pane.query_one("#plugins-list")
        nvim_index = next(
            index
            for index in range(option_list.option_count)
            if option_list.get_option_at_index(index).id == "plugin__nvim"
        )
        assert "[✓]" in option_list.get_option_at_index(nvim_index).prompt.plain

        _highlight(pane, "nvim")
        pane.action_toggle_install_mark()
        await page.wait_for(lambda _s: not pane._marked_install)
        assert "[✓]" not in option_list.get_option_at_index(nvim_index).prompt.plain


async def test_plugins_pane_toggle_install_mark_noops_for_installed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_other_panes(monkeypatch)
    _patch_catalog(monkeypatch, catalog=_catalog())
    async with AcePage() as page:
        pane = await _open_plugins_pane(page)
        messages = _spy_notify(monkeypatch, pane)
        _highlight(pane, "github")
        pane.action_toggle_install_mark()
        await page.pause()
        assert pane._marked_install == set()
        assert messages and messages[0][1] == "warning"
        assert "installable" in messages[0][0]


async def test_plugins_pane_escape_clears_install_marks_first(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_other_panes(monkeypatch)
    _patch_catalog(monkeypatch, catalog=_catalog())
    async with AcePage() as page:
        pane = await _open_plugins_pane(page)
        _highlight(pane, "nvim")
        pane.action_toggle_install_mark()
        await page.wait_for(lambda _s: pane._marked_install == {"nvim"})

        pane.action_clear_install_marks_or_close()
        await page.wait_for(lambda _s: not pane._marked_install)

        assert "esc clear" not in pane._hints()
        assert "esc" in pane._hints()


async def test_plugins_pane_prunes_stale_install_marks_on_reload(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_other_panes(monkeypatch)
    _patch_catalog(monkeypatch, catalog=_catalog())
    async with AcePage() as page:
        pane = await _open_plugins_pane(page)
        pane._marked_install.update({"nvim", "github", "missing"})

        pane._render_all()

        assert pane._marked_install == {"nvim"}


async def test_plugins_pane_install_already_installed_toasts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_other_panes(monkeypatch)
    _patch_catalog(monkeypatch, catalog=_catalog())
    planned: list[int] = []
    monkeypatch.setattr(pbp, "_plan_install_preview", lambda *a, **k: planned.append(1))
    async with AcePage() as page:
        pane = await _open_plugins_pane(page)
        messages = _spy_notify(monkeypatch, pane)
        _highlight(pane, "github")  # installed
        pane.action_install()
        await page.pause()
        assert not planned  # short-circuited before planning
        assert messages and "already installed" in messages[0][0]


async def test_plugins_pane_install_marked_set_takes_batch_path(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    _patch_other_panes(monkeypatch)
    calls = _patch_catalog_recording(monkeypatch, catalog=_catalog())
    receipt_file = tmp_path / "pending_update_toast.json"
    monkeypatch.setattr(update_receipt, "_PENDING_UPDATE_TOAST_FILE", receipt_file)
    batch_plan = _ready_many_plan(("acme", "nvim"))
    single_plans: list[str] = []
    batch_plans: list[tuple[str, ...]] = []
    monkeypatch.setattr(
        pbp,
        "_plan_install_preview",
        lambda name, *, offline: single_plans.append(name),
    )
    monkeypatch.setattr(
        pbp,
        "_plan_install_many_preview",
        lambda names, *, offline: (
            batch_plans.append(names) or pbp._InstallManyPreview(plan=batch_plan)
        ),
    )
    executed: list[InstallManyReady] = []

    def _fake_execute(plan: InstallManyReady, **_kw: object) -> InstallManyOutcome:
        executed.append(plan)
        return InstallManyOutcome(
            plan=plan,
            change_set=UvChangeSet(
                changes=(
                    UvPackageChange(
                        name="sase-acme", kind=ChangeKind.ADDED, new_version="0.1.0"
                    ),
                    UvPackageChange(
                        name="sase-nvim", kind=ChangeKind.ADDED, new_version="2.0.0"
                    ),
                )
            ),
            groups=(),
            elapsed=2.0,
        )

    monkeypatch.setattr(pbp, "execute_install_many", _fake_execute)
    async with AcePage() as page:
        pane = await _open_plugins_pane(page)
        initial = len(calls)
        messages = _spy_notify(monkeypatch, pane)
        restart_calls: list[bool] = []
        monkeypatch.setattr(
            page.app,
            "_restart_tui",
            lambda *, restart_axe: restart_calls.append(restart_axe),
        )
        pane._marked_install.update({"nvim", "acme"})
        _highlight(pane, "github")  # marks take precedence over the cursor

        pane.action_install()
        await page.expect_modal("PluginActionConfirmModal")
        modal = page.app.screen
        assert isinstance(modal, PluginActionConfirmModal)
        preview = _render(modal._preview_renderable())
        assert "Install 2 plugins" in str(modal._title)
        assert "acme" in preview
        assert "nvim" in preview
        assert batch_plans == [("acme", "nvim")]
        assert single_plans == []

        modal.action_confirm()
        await page.wait_for(lambda _s: bool(executed) and bool(restart_calls))
        assert executed[0].argv == batch_plan.argv
        assert pane._marked_install == set()
        assert restart_calls == [True]
        assert len(calls) == initial
        assert any("restarting ACE" in message for message, _severity in messages)
        receipt = update_receipt.read_and_clear_pending_update_toast()
        assert receipt is not None
        assert [plugin.name for plugin in receipt.plugins] == [
            "sase-acme",
            "sase-nvim",
        ]


async def test_plugins_pane_install_disabled_when_not_uv_tool(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_other_panes(monkeypatch)
    _patch_catalog(monkeypatch, catalog=_catalog())
    planned: list[int] = []
    monkeypatch.setattr(pbp, "_plan_install_preview", lambda *a, **k: planned.append(1))
    async with AcePage() as page:
        pane = await _open_plugins_pane(page)
        pane._uv_tool = _not_uv_tool()
        messages = _spy_notify(monkeypatch, pane)
        _highlight(pane, "nvim")
        pane.action_install()
        await page.pause()
        assert pane._plan_worker is None
        assert not planned
        assert messages and messages[0][1] == "warning"
        assert "uv tool install" in messages[0][0]
        # Affordances surface the disabled state.
        assert "i install" not in pane._hints()
        assert "unavailable" in pane._summary_text().plain


async def test_plugins_pane_install_not_found_toasts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_other_panes(monkeypatch)
    _patch_catalog(monkeypatch, catalog=_catalog())
    preview = pbp._InstallPreview(
        index_plan=InstallNotFound(query="nvim", suggestions=())
    )
    monkeypatch.setattr(pbp, "_plan_install_preview", lambda name, *, offline: preview)
    async with AcePage() as page:
        pane = await _open_plugins_pane(page)
        messages = _spy_notify(monkeypatch, pane)
        _highlight(pane, "nvim")
        pane.action_install()
        await page.wait_for(lambda _s: bool(messages))
        message, severity = messages[0]
        assert "No plugin named 'nvim'" in message
        assert severity == "error"


async def test_plugins_pane_install_confirm_executes_and_restarts(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    _patch_other_panes(monkeypatch)
    calls = _patch_catalog_recording(monkeypatch, catalog=_catalog())
    receipt_file = tmp_path / "pending_update_toast.json"
    monkeypatch.setattr(update_receipt, "_PENDING_UPDATE_TOAST_FILE", receipt_file)
    monkeypatch.setattr(
        pbp, "_plan_install_preview", lambda name, *, offline: _ready_preview(name)
    )
    executed: list[InstallReady] = []

    def _fake_execute(plan: InstallReady, **_kw: object) -> InstallOutcome:
        executed.append(plan)
        return InstallOutcome(
            plan=plan,
            change_set=UvChangeSet(
                changes=(
                    UvPackageChange(
                        name="sase-nvim", kind=ChangeKind.ADDED, new_version="2.0.0"
                    ),
                )
            ),
            groups=(),
            elapsed=1.5,
        )

    monkeypatch.setattr(pbp, "execute_install", _fake_execute)
    async with AcePage() as page:
        pane = await _open_plugins_pane(page)
        initial = len(calls)
        messages = _spy_notify(monkeypatch, pane)
        restart_calls: list[bool] = []
        monkeypatch.setattr(
            page.app,
            "_restart_tui",
            lambda *, restart_axe: restart_calls.append(restart_axe),
        )
        _highlight(pane, "nvim")
        await page.wait_for(lambda _s: pane._highlighted_name() == "nvim")
        pane.action_install()
        await page.expect_modal("PluginActionConfirmModal")
        modal = page.app.screen
        assert isinstance(modal, PluginActionConfirmModal)
        modal.action_confirm()  # accept the default index variant
        # The tracked task runs execute_install, then restarts ACE + axe.
        await page.wait_for(lambda _s: bool(executed) and bool(restart_calls))
        assert executed[0].spec.display_name == "nvim"
        assert executed[0].spec.source == "catalog"
        assert restart_calls == [True]
        assert len(calls) == initial
        assert any("restarting ACE" in message for message, _severity in messages)
        receipt = update_receipt.read_and_clear_pending_update_toast()
        assert receipt is not None
        assert receipt.plugins
        assert receipt.plugins[0].name == "sase-nvim"
        assert receipt.plugins[0].old is None
        assert receipt.plugins[0].new == "2.0.0"


async def test_plugins_pane_install_no_change_refreshes_without_restart(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_other_panes(monkeypatch)
    calls = _patch_catalog_recording(monkeypatch, catalog=_catalog())
    monkeypatch.setattr(
        pbp, "_plan_install_preview", lambda name, *, offline: _ready_preview(name)
    )
    executed: list[InstallReady] = []

    def _fake_execute(plan: InstallReady, **_kw: object) -> InstallOutcome:
        executed.append(plan)
        return InstallOutcome(
            plan=plan,
            change_set=UvChangeSet(),
            groups=(),
            elapsed=0.1,
        )

    monkeypatch.setattr(pbp, "execute_install", _fake_execute)
    async with AcePage() as page:
        pane = await _open_plugins_pane(page)
        initial = len(calls)
        restart_calls: list[bool] = []
        monkeypatch.setattr(
            page.app,
            "_restart_tui",
            lambda *, restart_axe: restart_calls.append(restart_axe),
        )
        _highlight(pane, "nvim")
        await page.wait_for(lambda _s: pane._highlighted_name() == "nvim")
        pane.action_install()
        await page.expect_modal("PluginActionConfirmModal")
        modal = page.app.screen
        assert isinstance(modal, PluginActionConfirmModal)
        modal.action_confirm()

        await page.wait_for(lambda _s: bool(executed) and len(calls) > initial)
        assert restart_calls == []


async def test_plugins_pane_install_git_variant_executed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_other_panes(monkeypatch)
    _patch_catalog(monkeypatch, catalog=_catalog())
    monkeypatch.setattr(
        pbp, "_plan_install_preview", lambda name, *, offline: _ready_preview(name)
    )
    executed: list[InstallReady] = []

    def _fake_execute(plan: InstallReady, **_kw: object) -> InstallOutcome:
        executed.append(plan)
        return InstallOutcome(
            plan=plan, change_set=UvChangeSet(), groups=(), elapsed=0.2
        )

    monkeypatch.setattr(pbp, "execute_install", _fake_execute)
    async with AcePage() as page:
        pane = await _open_plugins_pane(page)
        _highlight(pane, "nvim")
        await page.wait_for(lambda _s: pane._highlighted_name() == "nvim")
        pane.action_install()
        await page.expect_modal("PluginActionConfirmModal")
        modal = page.app.screen
        assert isinstance(modal, PluginActionConfirmModal)
        modal.action_toggle_source()  # index -> git
        modal.action_confirm()
        await page.wait_for(lambda _s: bool(executed))
        assert executed[0].spec.source == "git"


async def test_plugin_action_modal_toggle_and_confirm(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    variants = [
        PluginActionVariant(
            key="index",
            label="from index",
            argv=("uv", "tool", "install", "sase-nvim"),
            summary="Installs nvim  (from catalog)",
        ),
        PluginActionVariant(
            key="git",
            label="from git",
            argv=("uv", "tool", "install", "git+https://example/sase-nvim"),
            summary="Installs nvim  (from git)",
        ),
    ]
    async with AcePage() as page:
        results: list[PluginActionConfirmResult | None] = []
        modal = PluginActionConfirmModal(
            title="Install nvim", intro="Confirm", variants=variants
        )
        page.app.push_screen(modal, results.append)
        await page.expect_modal("PluginActionConfirmModal")
        assert modal._index == 0
        modal.action_toggle_source()
        assert modal._index == 1
        modal.action_confirm()
        await page.wait_for(lambda _s: bool(results))
        assert results[0] == PluginActionConfirmResult("git")


async def test_plugin_action_modal_cancel_returns_none(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    variants = [
        PluginActionVariant(
            key="update",
            label="update",
            argv=("uv", "tool", "install", "sase-nvim"),
            summary="Upgrades nvim",
        )
    ]
    async with AcePage() as page:
        results: list[PluginActionConfirmResult | None] = []
        modal = PluginActionConfirmModal(
            title="Update nvim", intro="Confirm", variants=variants
        )
        page.app.push_screen(modal, results.append)
        await page.expect_modal("PluginActionConfirmModal")
        # A single variant offers no source toggle.
        assert len(modal._variants) == 1
        modal.action_cancel()
        await page.wait_for(lambda _s: bool(results))
        assert results[0] is None


def _modal_variant() -> PluginActionVariant:
    return PluginActionVariant(
        key="update",
        label="update",
        argv=("uv", "tool", "install", "sase-nvim"),
        summary="Upgrades nvim",
    )


async def test_plugin_action_modal_without_loader_has_no_commits_box() -> None:
    async with AcePage() as page:
        modal = PluginActionConfirmModal(
            title="Update nvim",
            intro="Confirm",
            variants=(_modal_variant(),),
        )
        page.app.push_screen(modal)
        await page.expect_modal("PluginActionConfirmModal")

        assert len(modal.query("#plugin-action-commits")) == 0
        await page.press("ctrl+d")
        await page.press("ctrl+u")
        assert page.app.screen is modal


async def test_plugin_action_modal_loads_grouped_incoming_commits() -> None:
    groups = (
        RepoIncomingCommits(
            "sase",
            IncomingCommits(
                total=2,
                commits=(
                    CommitSummary("abc1234", "Newest core change"),
                    CommitSummary("def5678", "Older core change"),
                ),
                source="github",
            ),
        ),
        RepoIncomingCommits(
            "github",
            IncomingCommits(
                total=1,
                commits=(CommitSummary("fff0000", "Plugin change"),),
                source="github",
            ),
        ),
    )

    async with AcePage() as page:
        modal = PluginActionConfirmModal(
            title="Update SASE",
            intro="Confirm",
            variants=(_modal_variant(),),
            incoming_commits_loader=lambda: groups,
        )
        page.app.push_screen(modal)
        await page.expect_modal("PluginActionConfirmModal")
        await page.wait_for(lambda _s: len(modal.query("#plugin-action-commits")) > 0)

        body = modal.query_one("#plugin-action-commits-body", Static)
        await page.wait_for(
            lambda _s: (
                "↑ sase — 2 incoming commits" in _render(body.content)
                and "↑ github — 1 incoming commit" in _render(body.content)
            )
        )
        scroll = modal.query_one("#plugin-action-commits", VerticalScroll)
        await page.pause()
        assert int(scroll.max_scroll_y) == 0
        assert scroll.border_subtitle == ""
        await page.press("ctrl+d")
        await page.press("ctrl+u")
        assert scroll.scroll_y == 0


async def test_plugin_action_modal_summarizes_long_grouped_incoming_commits() -> None:
    groups = (
        RepoIncomingCommits(
            "sase",
            IncomingCommits(
                total=300,
                commits=tuple(
                    CommitSummary(f"{idx:07x}", f"SASE change {idx}")
                    for idx in range(250)
                ),
                source="git",
            ),
        ),
        RepoIncomingCommits(
            "sase-core",
            IncomingCommits(
                total=2,
                commits=(
                    CommitSummary("abc1234", "Core change"),
                    CommitSummary("def5678", "Core follow-up"),
                ),
                source="git",
            ),
        ),
        RepoIncomingCommits(
            "github",
            IncomingCommits(
                total=1,
                commits=(CommitSummary("fff0000", "Plugin change"),),
                source="git",
            ),
        ),
    )

    async with AcePage(size=(100, 24)) as page:
        modal = PluginActionConfirmModal(
            title="Update SASE",
            intro="Confirm",
            variants=(_modal_variant(),),
            incoming_commits_loader=lambda: groups,
        )
        page.app.push_screen(modal)
        await page.expect_modal("PluginActionConfirmModal")
        await page.wait_for(lambda _s: len(modal.query("#plugin-action-commits")) > 0)

        body = modal.query_one("#plugin-action-commits-body", Static)
        await page.wait_for(lambda _s: "SASE change 0" in _render(body.content))
        rendered = _render(body.content)
        first_detail = rendered.index("SASE change 0")
        assert rendered.index("↑ sase-core — 2 incoming commits") < first_detail
        assert rendered.index("↑ github — 1 incoming commit") < first_detail
        assert "↑ sase — 300 incoming commits (250 shown, +50 more)" in rendered


async def test_plugin_action_modal_empty_incoming_commits_hides_box() -> None:
    async with AcePage() as page:
        modal = PluginActionConfirmModal(
            title="Update SASE",
            intro="Confirm",
            variants=(_modal_variant(),),
            incoming_commits_loader=lambda: (),
        )
        page.app.push_screen(modal)
        await page.expect_modal("PluginActionConfirmModal")
        await page.wait_for(lambda _s: len(modal.query("#plugin-action-commits")) > 0)

        scroll = modal.query_one("#plugin-action-commits", VerticalScroll)
        await page.wait_for(lambda _s: not scroll.display)
        await page.press("ctrl+d")
        await page.press("ctrl+u")
        assert scroll.scroll_y == 0


async def test_plugin_action_modal_incoming_commits_loader_error() -> None:
    def loader() -> tuple[RepoIncomingCommits, ...]:
        raise RuntimeError("boom")

    async with AcePage() as page:
        modal = PluginActionConfirmModal(
            title="Update SASE",
            intro="Confirm",
            variants=(_modal_variant(),),
            incoming_commits_loader=loader,
        )
        page.app.push_screen(modal)
        await page.expect_modal("PluginActionConfirmModal")
        await page.wait_for(lambda _s: len(modal.query("#plugin-action-commits")) > 0)

        body = modal.query_one("#plugin-action-commits-body", Static)
        await page.wait_for(
            lambda _s: "incoming commits unavailable (boom)" in _render(body.content)
        )


@pytest.mark.parametrize("size", [(100, 24), (120, 40)])
async def test_plugin_action_modal_scrolls_incoming_commits(
    size: tuple[int, int],
) -> None:
    groups = (
        RepoIncomingCommits(
            "sase",
            IncomingCommits(
                total=60,
                commits=tuple(
                    CommitSummary(f"{idx:07x}", f"Incoming SASE change {idx}")
                    for idx in range(60)
                ),
                source="git",
            ),
        ),
        RepoIncomingCommits(
            "github",
            IncomingCommits(
                total=8,
                commits=tuple(
                    CommitSummary(f"f{idx:06x}", f"Incoming plugin change {idx}")
                    for idx in range(8)
                ),
                source="git",
            ),
        ),
    )

    async with AcePage(size=size) as page:
        modal = PluginActionConfirmModal(
            title="Update SASE",
            intro="Confirm",
            variants=(_modal_variant(),),
            incoming_commits_loader=lambda: groups,
        )
        page.app.push_screen(modal)
        await page.expect_modal("PluginActionConfirmModal")
        await page.wait_for(lambda _s: len(modal.query("#plugin-action-commits")) > 0)

        scroll = modal.query_one("#plugin-action-commits", VerticalScroll)
        await page.wait_for(lambda _s: int(scroll.max_scroll_y) > 0)
        await page.wait_for(lambda _s: scroll.border_subtitle == "ctrl+d/u scroll")

        container = modal.query_one("#plugin-action-container")
        buttons = modal.query_one("#plugin-action-buttons")
        bounds = container.content_region
        for child in (scroll, buttons):
            assert child.region.x >= bounds.x
            assert child.region.y >= bounds.y
            assert child.region.right <= bounds.right
            assert child.region.bottom <= bounds.bottom

        half_page = max(1, scroll.scrollable_content_region.height // 2)
        max_scroll_y = int(scroll.max_scroll_y)
        assert scroll.scroll_y == 0

        await page.press("ctrl+u")
        await page.pause()
        assert scroll.scroll_y == 0

        await page.press("ctrl+d")
        await page.pause()
        assert scroll.scroll_y == min(half_page, max_scroll_y)

        near_bottom = max(0, max_scroll_y - half_page + 1)
        scroll.scroll_to(y=near_bottom, animate=False)
        await page.pause()
        assert scroll.scroll_y == near_bottom
        await page.press("ctrl+d")
        await page.pause()
        assert scroll.scroll_y == max_scroll_y
        await page.press("ctrl+d")
        await page.pause()
        assert scroll.scroll_y == max_scroll_y

        await page.press("ctrl+u")
        await page.pause()
        assert scroll.scroll_y == max(0, max_scroll_y - half_page)
        near_top = min(max_scroll_y, max(0, half_page - 1))
        scroll.scroll_to(y=near_top, animate=False)
        await page.pause()
        assert scroll.scroll_y == near_top
        await page.press("ctrl+u")
        await page.pause()
        assert scroll.scroll_y == 0
        await page.press("ctrl+u")
        await page.pause()
        assert scroll.scroll_y == 0
