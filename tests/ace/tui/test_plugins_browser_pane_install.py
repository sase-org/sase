"""Install action tests for the Plugins pane and action confirm modal."""

from __future__ import annotations

import pytest

from sase.ace import update_receipt
from sase.ace.testing import AcePage
from sase.ace.tui.modals import plugins_browser_pane as pbp
from sase.ace.tui.modals.plugin_action_confirm_modal import PluginActionConfirmModal
from sase.plugins.operations import (
    InstallManyOutcome,
    InstallManyReady,
    InstallNotFound,
    InstallOutcome,
)
from sase.uv_tool.runner import ChangeKind, UvChangeSet, UvPackageChange
from tests.ace.tui._plugins_browser_pane_helpers import (
    _catalog,
    _complete_durable_update,
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
        acme_entry = pane._entry_by_name("acme")
        assert acme_entry is not None
        acme_row = pane._row_text(acme_entry).plain
        assert "[✓]" in acme_row
        assert "acme-corp/sase-acme" in acme_row

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
    preview = _ready_preview("nvim")
    monkeypatch.setattr(pbp, "_plan_install_preview", lambda name, *, offline: preview)
    outcome = InstallOutcome(
        plan=preview.index_plan,
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
    async with AcePage() as page:
        pane = await _open_plugins_pane(page)
        submissions = _complete_durable_update(
            monkeypatch,
            page.app,
            outcome=outcome,
            message="Installed nvim v2.0.0 in 1.5s",
        )
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
        await page.wait_for(lambda _s: bool(restart_calls))
        [(args, kwargs)] = submissions
        assert args == (["sase", "plugin", "install", "nvim", "--json"],)
        assert kwargs["request"] == {"plugin": "nvim", "source": "catalog"}
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
    preview = _ready_preview("nvim")
    monkeypatch.setattr(pbp, "_plan_install_preview", lambda name, *, offline: preview)
    outcome = InstallOutcome(
        plan=preview.index_plan,
        change_set=UvChangeSet(),
        groups=(),
        elapsed=0.1,
    )
    async with AcePage() as page:
        pane = await _open_plugins_pane(page)
        _complete_durable_update(
            monkeypatch,
            page.app,
            outcome=outcome,
            message="Plugins already up to date.",
        )
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

        await page.wait_for(lambda _s: len(calls) > initial)
        assert restart_calls == []


async def test_plugins_pane_install_git_variant_executed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_other_panes(monkeypatch)
    _patch_catalog(monkeypatch, catalog=_catalog())
    preview = _ready_preview("nvim")
    assert preview.git_plan is not None
    monkeypatch.setattr(pbp, "_plan_install_preview", lambda name, *, offline: preview)
    outcome = InstallOutcome(
        plan=preview.git_plan,
        change_set=UvChangeSet(),
        groups=(),
        elapsed=0.2,
    )
    async with AcePage() as page:
        pane = await _open_plugins_pane(page)
        submissions = _complete_durable_update(
            monkeypatch,
            page.app,
            outcome=outcome,
            message="Plugins already up to date.",
        )
        _highlight(pane, "nvim")
        await page.wait_for(lambda _s: pane._highlighted_name() == "nvim")
        pane.action_install()
        await page.expect_modal("PluginActionConfirmModal")
        modal = page.app.screen
        assert isinstance(modal, PluginActionConfirmModal)
        modal.action_toggle_source()  # index -> git
        modal.action_confirm()
        await page.wait_for(lambda _s: bool(submissions))
        [(args, kwargs)] = submissions
        assert args == (["sase", "plugin", "install", "nvim", "--json", "--git"],)
        assert kwargs["request"] == {"plugin": "nvim", "source": "git"}
