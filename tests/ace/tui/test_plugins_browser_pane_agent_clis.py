"""Updates-pane sub-tab and Agent CLIs browser tests."""

from __future__ import annotations

from collections.abc import Mapping
from types import SimpleNamespace
from typing import Any

import pytest
from textual.widgets import ContentSwitcher, OptionList

from sase.ace.testing import AcePage
from sase.ace.tui.modals import plugins_browser_loading as loading
from sase.ace.tui.modals import plugins_browser_pane as pbp
from sase.ace.tui.modals.config_center_modal import ConfigCenterModal
from sase.ace.tui.modals.config_center_session import AdminCenterSessionState
from sase.ace.tui.modals.plugin_action_confirm_modal import PluginActionConfirmModal
from sase.ace.tui.modals.plugins_browser_pane import PluginsBrowserPane
from sase.agent_clis import operations
from sase.agent_clis.models import (
    AgentCliUpdateResult,
    AgentCliStatus,
    InstallMethod,
    AgentCliUpdatesReady,
    UpdateResultStatus,
)

from tests.ace.tui._plugins_browser_pane_helpers import (
    _agent_cli_statuses,
    _agent_cli_update_run,
    _catalog,
    _core_versions,
    _open_plugins_pane,
    _patch_catalog,
    _patch_other_panes,
    _render,
)
from tests.ace.tui._proc_submit_signature_helpers import (
    assert_session_worker_submit_signature,
)


async def test_updates_subtabs_cycle_and_gate_plugin_actions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_other_panes(monkeypatch)
    _patch_catalog(
        monkeypatch,
        catalog=_catalog(),
        agent_cli_statuses=_agent_cli_statuses(),
        agent_cli_colors={"claude": "#D97757", "codex": "#10A37F"},
    )

    async with AcePage() as page:
        pane = await _open_plugins_pane(page)
        switcher = pane.query_one("#updates-subtab-switcher", ContentSwitcher)
        assert pane._active_subtab == "plugins"

        pane.action_cycle_subtab()
        assert pane._active_subtab == "agent-clis"
        assert switcher.current == "updates-subtab-agent-clis"
        assert pane.check_action("install", ()) is False
        assert pane.check_action("update_agent_clis", ()) is True

        pane.action_cycle_subtab()
        assert pane._active_subtab == "core"
        assert switcher.current == "updates-subtab-core"
        assert pane.check_action("next_option", ()) is False

        pane.action_cycle_subtab_reverse()
        assert pane._active_subtab == "agent-clis"


async def test_agent_cli_session_restores_subtab_and_row_by_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_other_panes(monkeypatch)
    _patch_catalog(
        monkeypatch,
        catalog=_catalog(),
        agent_cli_statuses=_agent_cli_statuses(),
    )
    state = AdminCenterSessionState()
    state.updates.active_subtab = "agent-clis"
    state.updates.agent_clis.record("codex", 0)

    async with AcePage() as page:
        modal = ConfigCenterModal(initial_tab="updates", session_state=state)
        page.app.push_screen(modal)
        await page.expect_modal("ConfigCenterModal")
        await page.wait_for(lambda _s: bool(modal.query("#updates")))
        pane = modal.query_one("#updates", PluginsBrowserPane)
        await page.wait_for(lambda _s: not pane._loading)

        option_list = pane.query_one("#agent-clis-list", OptionList)
        assert pane._active_subtab == "agent-clis"
        assert option_list.highlighted == 1
        assert state.updates.agent_clis.identity == "codex"


async def test_agent_cli_pane_uses_shared_filtered_inventory(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_other_panes(monkeypatch)
    payload = {
        "providers": {
            "claude": {
                "autodetect_cli_name": "claude",
                "install": {"display_name": "Claude Code"},
            },
            "fakey": {
                "autodetect_cli_name": "fakey",
                "hidden_from_agent_cli_management": True,
                "install": {"display_name": "Fakey"},
            },
        }
    }

    def _detect(
        providers: Mapping[str, Mapping[str, Any]],
        *,
        env: Mapping[str, str] | None,
        run_fn: Any,
    ) -> tuple[AgentCliStatus, ...]:
        del env, run_fn
        return tuple(
            AgentCliStatus(
                name=name,
                display_name=str(metadata["install"]["display_name"]),
                binary=str(metadata["autodetect_cli_name"]),
                executable=f"/bin/{name}",
                installed_version="1.0.0",
                latest_version=None,
                install_method=InstallMethod.SELF_MANAGED,
                update_available=False,
                docs_url=None,
                install_hint=f"install {name}",
                self_update_argv=("update",),
            )
            for name, metadata in providers.items()
        )

    monkeypatch.setattr(
        operations.llm_registry,
        "get_llm_metadata_payload",
        lambda: payload,
    )
    monkeypatch.setattr(operations, "detect_agent_cli_statuses", _detect)
    monkeypatch.setattr(
        loading,
        "provider_cli_status_color_map",
        lambda: {"claude": "#D97757", "fakey": "#FF5FAF"},
    )
    statuses, error, colors = loading._collect_agent_clis_for_pane(
        refresh=False,
        offline=True,
    )
    assert error is None
    assert [status.name for status in statuses] == ["claude"]

    _patch_catalog(
        monkeypatch,
        catalog=_catalog(),
        agent_cli_statuses=statuses,
        agent_cli_colors=colors,
    )

    async with AcePage() as page:
        pane = await _open_plugins_pane(page)
        pane._switch_to_subtab("agent-clis")
        option_list = pane.query_one("#agent-clis-list", OptionList)

        ids = [
            option_list.get_option_at_index(index).id
            for index in range(option_list.option_count)
        ]
        assert ids == ["agent-cli__claude"]
        assert "agent-cli__fakey" not in ids
        assert pane._agent_cli_by_name("fakey") is None
        current = pane._current_agent_cli()
        assert current is not None
        assert current.name == "claude"
        assert "1 agent CLIs · 1 installed" in _render(pane._agent_cli_summary())


async def test_updates_subtabs_handle_brackets_from_core_and_lists(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_other_panes(monkeypatch)
    _patch_catalog(
        monkeypatch,
        catalog=_catalog(),
        agent_cli_statuses=_agent_cli_statuses(),
    )

    async with AcePage() as page:
        modal = ConfigCenterModal(initial_tab="updates")
        page.app.push_screen(modal)
        await page.expect_modal("ConfigCenterModal")
        await page.wait_for(lambda _s: bool(modal.query("#updates")))
        pane = modal.query_one("#updates", PluginsBrowserPane)
        await page.wait_for(lambda _s: not pane._loading)
        plugins_list = pane.query_one("#plugins-list", OptionList)
        agent_clis_list = pane.query_one("#agent-clis-list", OptionList)

        assert pane._active_subtab == "core"
        assert page.app.focused is pane

        await page.press("right_square_bracket")
        await page.wait_for(lambda _s: pane._active_subtab == "plugins")
        assert page.app.focused is plugins_list

        await page.press("right_square_bracket")
        await page.wait_for(lambda _s: pane._active_subtab == "agent-clis")
        assert page.app.focused is agent_clis_list

        await page.press("right_square_bracket")
        await page.wait_for(lambda _s: pane._active_subtab == "core")
        assert page.app.focused is pane

        await page.press("left_square_bracket")
        await page.wait_for(lambda _s: pane._active_subtab == "agent-clis")
        assert page.app.focused is agent_clis_list

        await page.press("left_square_bracket")
        await page.wait_for(lambda _s: pane._active_subtab == "plugins")
        assert page.app.focused is plugins_list

        await page.press("left_square_bracket")
        await page.wait_for(lambda _s: pane._active_subtab == "core")
        assert page.app.focused is pane


async def test_updates_subtab_hints_share_projects_wording(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_other_panes(monkeypatch)
    _patch_catalog(monkeypatch, catalog=_catalog())

    async with AcePage() as page:
        pane = await _open_plugins_pane(page)
        hints = (pane._core_hints(), pane._hints(), pane._agent_cli_hints())

        assert all("[ / ] sub-tab" in hint for hint in hints)
        assert all("]/[ sub-tab" not in hint for hint in hints)
        assert all("a sync agents" in hint for hint in hints)


async def test_agent_cli_marks_patch_rows_and_escape_clears_first(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_other_panes(monkeypatch)
    _patch_catalog(
        monkeypatch,
        catalog=_catalog(),
        agent_cli_statuses=_agent_cli_statuses(),
    )

    async with AcePage() as page:
        pane = await _open_plugins_pane(page)
        pane._switch_to_subtab("agent-clis")
        option_list = pane.query_one("#agent-clis-list", OptionList)
        assert option_list.highlighted == 0

        pane.action_toggle_mark()
        assert pane._marked_agent_clis == {"claude"}
        claude_row = option_list.get_option_at_index(0).prompt
        row_text = claude_row.plain if hasattr(claude_row, "plain") else str(claude_row)
        assert "[✓]" in row_text

        pane.action_clear_marks_or_close()
        assert pane._marked_agent_clis == set()
        assert page.app.screen.__class__.__name__ == "ConfigCenterModal"


async def test_agent_cli_update_plan_confirm_and_tracked_execution(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_other_panes(monkeypatch)
    statuses = _agent_cli_statuses()
    _patch_catalog(
        monkeypatch,
        catalog=_catalog(),
        agent_cli_statuses=statuses,
    )
    submitted: dict[str, Any] = {}

    async with AcePage() as page:
        pane = await _open_plugins_pane(page)
        pane._switch_to_subtab("agent-clis")

        def submit(*args: Any, **kwargs: Any) -> object:
            assert_session_worker_submit_signature(args, kwargs)
            submitted["args"] = args
            submitted.update(kwargs)
            return object()

        monkeypatch.setattr(page.app, "_submit_session_worker", submit)
        pane.action_update_agent_clis()
        await page.expect_modal("PluginActionConfirmModal")
        modal = page.app.screen
        assert isinstance(modal, PluginActionConfirmModal)
        variant = modal._variants[0]
        assert variant.items_label == "Commands"
        assert any("claude update" in item for item in variant.items)
        assert any(
            "Homebrew installs require a manual upgrade" in item
            and "developers.openai.com" in item
            for item in variant.skipped
        )

        await page.press("y")
        await page.expect_modal("ConfigCenterModal")
        assert submitted["dedup_key"] == "agent-cli-update"
        assert submitted["exclusive_scopes"] == ("agent-cli-update",)
        assert (
            submitted["duplicate_message"] == "An agent CLI update is already running."
        )

        plan = pane._make_agent_cli_update_plan(None, all_clis=True)
        assert isinstance(plan, AgentCliUpdatesReady)
        result = AgentCliUpdateResult(
            name="claude",
            display_name="Claude Code",
            status=UpdateResultStatus.UPDATED,
            old_version="1.0.0",
            new_version="1.1.0",
            command=("/home/dev/.local/bin/claude", "update"),
            docs_url="https://code.claude.com/docs/en/setup",
        )
        monkeypatch.setattr(
            pbp,
            "_execute_agent_cli_updates",
            lambda *_args, **_kwargs: (result,),
        )
        task_result = submitted["args"][1]()
        assert task_result.success is True
        assert task_result.payload == (result,)

        reloads: list[bool] = []
        monkeypatch.setattr(
            pane,
            "_start_load",
            lambda *, force: reloads.append(force),
        )
        submitted["on_complete"](
            SimpleNamespace(
                payload=(result,),
                message="Claude Code: updated 1.0.0 → 1.1.0",
                success=True,
            )
        )
        assert pane._agent_cli_results["claude"] == result
        assert reloads == [False]


async def test_update_sase_action_remains_pane_wide(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_other_panes(monkeypatch)
    _patch_catalog(
        monkeypatch,
        catalog=_catalog(),
        agent_cli_statuses=_agent_cli_statuses(),
    )

    async with AcePage() as page:
        pane = await _open_plugins_pane(page)
        calls: list[str] = []
        monkeypatch.setattr(
            pane,
            "_start_sase_update_preview",
            lambda **_kwargs: calls.append(pane._active_subtab),
        )
        for subtab in ("core", "plugins", "agent-clis"):
            pane._switch_to_subtab(subtab)
            pane.action_update_sase()
        assert calls == ["core", "plugins", "agent-clis"]


class _Reporter:
    def phase(self, _label: str) -> None:
        pass

    def section(self, _title: str) -> None:
        pass

    def log(self, _text: str, *, stream: str = "stdout") -> None:
        del stream

    def subprocess_run_fn(self) -> Any:
        raise AssertionError("executor was stubbed; no subprocess should run")


async def test_agent_cli_history_populates_pane_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_other_panes(monkeypatch)
    run = _agent_cli_update_run()
    _patch_catalog(
        monkeypatch,
        catalog=_catalog(),
        agent_cli_statuses=_agent_cli_statuses(),
        agent_cli_history=(run,),
    )

    async with AcePage() as page:
        pane = await _open_plugins_pane(page)
        assert pane._agent_cli_history == (run,)
        assert pane._agent_cli_history_error is None


async def test_agent_cli_history_defaults_when_loader_omits_fields(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_other_panes(monkeypatch)
    # A stubbed loader that predates the history fields must keep working —
    # every field is adopted via getattr(..., default).
    monkeypatch.setattr(
        pbp,
        "_load_plugins_catalog",
        lambda **_kw: SimpleNamespace(catalog=_catalog(), error=None, now=0.0),
    )

    async with AcePage() as page:
        pane = await _open_plugins_pane(page)
        assert pane._agent_cli_history == ()
        assert pane._agent_cli_history_error is None


def _patch_loading_collaborators(
    monkeypatch: pytest.MonkeyPatch,
    *,
    agent_cli_statuses: tuple[AgentCliStatus, ...],
) -> None:
    """Stub every non-history leg of ``load_plugins_catalog_for_pane``."""
    monkeypatch.setattr(loading, "probe_uv_tool", lambda: None)
    monkeypatch.setattr(loading, "load_merged_config", dict)
    monkeypatch.setattr(loading, "config_dev_root", lambda _config: "/tmp/dev")
    monkeypatch.setattr(
        loading,
        "_collect_core_versions_for_pane",
        lambda **_kwargs: _core_versions(),
    )
    monkeypatch.setattr(
        loading,
        "_collect_agent_clis_for_pane",
        lambda **_kwargs: (agent_cli_statuses, None, {}),
    )
    monkeypatch.setattr(loading, "load_plugin_catalog", lambda **_kwargs: _catalog())
    monkeypatch.setattr(loading, "enrich_with_latest", lambda loaded, **_kwargs: loaded)
    monkeypatch.setattr(
        loading,
        "_fetch_core_incoming_commits_for_pane",
        lambda *_args, **_kwargs: {},
    )


def test_agent_cli_history_read_failure_sets_error_and_preserves_statuses(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    statuses = _agent_cli_statuses()
    _patch_loading_collaborators(monkeypatch, agent_cli_statuses=statuses)

    def _raise(**_kwargs: Any) -> tuple[Any, ...]:
        raise OSError("disk gone")

    monkeypatch.setattr(pbp, "_read_agent_cli_update_runs", _raise)

    result = loading.load_plugins_catalog_for_pane(
        offline=True,
        incoming_commits_enabled=False,
        agent_cli_history_enabled=True,
        now=123.0,
    )

    assert result.agent_cli_history == ()
    assert result.agent_cli_history_error is not None
    assert "disk gone" in result.agent_cli_history_error
    assert result.agent_cli_statuses == statuses
    assert result.agent_cli_error is None


def test_agent_cli_history_disabled_skips_journal_read(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    statuses = _agent_cli_statuses()
    _patch_loading_collaborators(monkeypatch, agent_cli_statuses=statuses)
    calls: list[dict[str, Any]] = []

    def _spy(**kwargs: Any) -> tuple[Any, ...]:
        calls.append(kwargs)
        raise AssertionError("must not be called while history is disabled")

    monkeypatch.setattr(pbp, "_read_agent_cli_update_runs", _spy)

    result = loading.load_plugins_catalog_for_pane(
        offline=True,
        incoming_commits_enabled=False,
        agent_cli_history_enabled=False,
        now=123.0,
    )

    assert calls == []
    assert result.agent_cli_history == ()
    assert result.agent_cli_history_error is None


def test_agent_cli_history_config_coerces_bad_values_to_defaults() -> None:
    config = pbp._load_agent_cli_history_config(
        lambda: {
            "ace": {
                "updates": {
                    "agent_cli_history": True,
                    "agent_cli_history_max_rows": 12,
                }
            }
        }
    )
    assert config.enabled is True
    assert config.max_rows == 12

    fallback = pbp._load_agent_cli_history_config(
        lambda: {
            "ace": {
                "updates": {
                    "agent_cli_history": "not-a-bool",
                    "agent_cli_history_max_rows": -3,
                }
            }
        }
    )
    assert fallback.enabled is True
    assert fallback.max_rows == 8

    non_integer = pbp._load_agent_cli_history_config(
        lambda: {
            "ace": {
                "updates": {"agent_cli_history_max_rows": "not-an-int"},
            }
        }
    )
    assert non_integer.max_rows == 8
