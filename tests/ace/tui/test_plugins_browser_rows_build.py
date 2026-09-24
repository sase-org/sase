"""Row building, capability derivation, error, and haystack tests."""

from __future__ import annotations

from sase.ace.tui.modals.plugins_browser_rows import (
    build_plugin_row,
    build_update_rows,
)
from sase.agent_clis.models import (
    AgentCliStatus,
    AgentCliUnknownName,
)
from sase.agent_clis.operations import plan_agent_cli_updates
from sase.plugins.catalog import PluginCatalog
from sase.plugins.installed import InstalledInfo
from sase.plugins.latest import LatestInfo
from sase.uv_tool.versions import CoreVersions
from tests.ace.tui._plugins_browser_rows_helpers import (
    _NOW,
    _core_package,
    _entry,
    _load_result,
    _manual_only_cli_status,
    _not_installed_cli_status,
    _not_uv_tool,
    _ready_cli_status,
)


# -- build_update_rows: one row per source -----------------------------------


def test_build_update_rows_one_row_per_source() -> None:
    catalog = PluginCatalog(
        fetched_at=_NOW,
        entries=(
            _entry(
                "github",
                owner="sase-org",
                installed=InstalledInfo(installed=True, version="1.0.0"),
                latest=LatestInfo(checked=True, version="1.1.0", source="index"),
            ),
            _entry("acme", owner="acme-corp"),
        ),
        from_cache=True,
        stale=False,
    )
    result = _load_result(
        core_versions=CoreVersions(packages=(_core_package(),)),
        catalog=catalog,
        agent_cli_statuses=(_ready_cli_status(),),
    )

    rows = build_update_rows(
        result, uv_tool=None, offline=False, plan_fn=plan_agent_cli_updates
    )

    assert [row.key for row in rows] == [
        "core:sase",
        "plugin:github",
        "plugin:acme",
        "cli:claude",
    ]
    core_row, github_row, acme_row, cli_row = rows
    assert (core_row.kind, core_row.section) == ("core", "sase")
    assert (github_row.kind, github_row.section) == ("plugin", "plugins-builtin")
    assert (acme_row.kind, acme_row.section) == ("plugin", "plugins-community")
    assert (cli_row.kind, cli_row.section) == ("agent-cli", "agent-clis")
    assert core_row.payload.name == "sase"
    assert github_row.payload.name == "github"
    assert cli_row.payload.name == "claude"


# -- plugin capability derivation --------------------------------------------


def test_plugin_capabilities_not_installed() -> None:
    row = build_plugin_row(_entry("nvim"), blocked=False)
    assert row.capabilities == frozenset({"install"})


def test_plugin_capabilities_installed_no_update() -> None:
    entry = _entry(
        "telegram",
        installed=InstalledInfo(installed=True, version="0.5.0"),
        latest=LatestInfo(checked=True, version="0.5.0", source="index"),
    )
    row = build_plugin_row(entry, blocked=False)
    assert row.capabilities == frozenset({"uninstall"})


def test_plugin_capabilities_installed_with_update() -> None:
    entry = _entry(
        "github",
        installed=InstalledInfo(installed=True, version="1.0.0"),
        latest=LatestInfo(checked=True, version="1.1.0", source="index"),
    )
    row = build_plugin_row(entry, blocked=False)
    assert row.capabilities == frozenset({"uninstall", "update"})


def test_plugin_capabilities_withdrawn_when_uv_tool_blocked() -> None:
    installed = _entry(
        "github",
        installed=InstalledInfo(installed=True, version="1.0.0"),
        latest=LatestInfo(checked=True, version="1.1.0", source="index"),
    )
    not_installed = _entry("nvim")
    assert build_plugin_row(installed, blocked=True).capabilities == frozenset()
    assert build_plugin_row(not_installed, blocked=True).capabilities == frozenset()


def test_build_update_rows_uv_tool_blocked_withdraws_plugin_capabilities() -> None:
    catalog = PluginCatalog(
        fetched_at=_NOW,
        entries=(
            _entry(
                "github",
                installed=InstalledInfo(installed=True, version="1.0.0"),
                latest=LatestInfo(checked=True, version="1.1.0", source="index"),
            ),
        ),
        from_cache=True,
        stale=False,
    )
    result = _load_result(catalog=catalog)
    rows = build_update_rows(result, uv_tool=_not_uv_tool(), offline=False)
    assert rows[0].capabilities == frozenset()


# -- agent-CLI capability derivation -----------------------------------------


def test_agent_cli_ready_update_carries_mark_update_not_manual() -> None:
    result = _load_result(agent_cli_statuses=(_ready_cli_status(),))
    rows = build_update_rows(
        result, uv_tool=None, offline=False, plan_fn=plan_agent_cli_updates
    )
    row = rows[0]
    assert "mark_update" in row.capabilities
    assert "manual" not in row.capabilities
    assert "history" in row.capabilities


def test_agent_cli_manual_only_with_newer_version_carries_manual_not_mark_update() -> (
    None
):
    result = _load_result(agent_cli_statuses=(_manual_only_cli_status(),))
    rows = build_update_rows(
        result, uv_tool=None, offline=False, plan_fn=plan_agent_cli_updates
    )
    row = rows[0]
    assert row.update_available is True
    assert "manual" in row.capabilities
    assert "mark_update" not in row.capabilities


def test_agent_cli_not_installed_has_no_update_capabilities() -> None:
    result = _load_result(agent_cli_statuses=(_not_installed_cli_status(),))
    rows = build_update_rows(
        result, uv_tool=None, offline=False, plan_fn=plan_agent_cli_updates
    )
    row = rows[0]
    assert row.capabilities == frozenset({"history"})


def test_agent_cli_unplannable_provider_degrades_to_no_mark_update() -> None:
    def _unknown_plan_fn(names, **_kwargs):
        query = names[0] if names else ""
        return AgentCliUnknownName(query=query, known_names=())

    result = _load_result(agent_cli_statuses=(_ready_cli_status(),))
    rows = build_update_rows(
        result, uv_tool=None, offline=False, plan_fn=_unknown_plan_fn
    )
    row = rows[0]
    assert row.capabilities == frozenset({"history"})


# -- error field, per kind ----------------------------------------------------


def test_error_field_per_kind() -> None:
    core_row = build_update_rows(
        _load_result(
            core_versions=CoreVersions(
                packages=(_core_package(latest_error="pypi unreachable"),)
            )
        ),
        uv_tool=None,
        offline=False,
    )[0]
    assert core_row.error == "pypi unreachable"

    plugin_row = build_plugin_row(
        _entry("github", latest=LatestInfo(checked=True, error="404")),
        blocked=False,
    )
    assert plugin_row.error == "404"

    status = _ready_cli_status()
    status_with_error = AgentCliStatus(
        **{**status.__dict__, "version_error": "probe timed out"}
    )
    row = build_update_rows(
        _load_result(agent_cli_statuses=(status_with_error,)),
        uv_tool=None,
        offline=False,
        plan_fn=plan_agent_cli_updates,
    )[0]
    assert row.error == "probe timed out"


# -- haystack content ----------------------------------------------------------


def test_plugin_haystack_contains_searchable_fields() -> None:
    row = build_plugin_row(
        _entry("github", description="GitHub VCS.", topics=("sase--plugin", "vcs")),
        blocked=False,
    )
    assert "github" in row.haystack
    assert "sase-github" in row.haystack
    assert "sase-org" in row.haystack
    assert "github vcs." in row.haystack
    assert "vcs" in row.haystack


def test_core_haystack_contains_name_and_distribution() -> None:
    row = build_update_rows(
        _load_result(core_versions=CoreVersions(packages=(_core_package(),))),
        uv_tool=None,
        offline=False,
    )[0]
    assert "sase" in row.haystack


def test_agent_cli_haystack_contains_provider_fields() -> None:
    row = build_update_rows(
        _load_result(agent_cli_statuses=(_ready_cli_status(),)),
        uv_tool=None,
        offline=False,
        plan_fn=plan_agent_cli_updates,
    )[0]
    assert "claude" in row.haystack
    assert "claude code" in row.haystack
    assert "self_managed" in row.haystack
