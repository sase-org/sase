"""Merged inventory selection, install routes, and sort tests."""

from __future__ import annotations

from sase.ace.tui.modals.plugins_browser_rows import (
    build_plugin_row,
    build_update_rows,
    select_rows,
)
from sase.agent_clis.models import (
    AgentCliStatus,
    InstallMethod,
)
from sase.agent_clis.operations import plan_agent_cli_updates
from sase.plugins.catalog import PluginCatalog
from sase.plugins.installed import InstalledInfo
from sase.plugins.latest import LatestInfo
from sase.uv_tool.versions import CorePackageVersion, CoreVersions
from tests.ace.tui._plugins_browser_rows_helpers import (
    _NOW,
    _cli_row,
    _core_package,
    _entry,
    _installable_cli_status,
    _load_result,
    _not_installed_cli_status,
    _ready_cli_status,
)


def test_select_rows_emits_sections_in_fixed_order_once() -> None:
    catalog = PluginCatalog(
        fetched_at=_NOW,
        entries=(
            _entry(
                "github",
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
    grouped = select_rows(rows, needle="")
    assert [header for header, _style, _rows in grouped] == [
        "── SASE ──",
        "── Plugins · Built-in ──",
        "── Plugins · Community ──",
        "── Agent CLIs ──",
    ]
    keys = [row.key for _header, _style, section in grouped for row in section]
    assert keys == ["core:sase", "plugin:github", "plugin:acme", "cli:claude"]


def test_select_rows_sorts_outdated_first_then_label() -> None:
    catalog = PluginCatalog(
        fetched_at=_NOW,
        entries=(
            _entry(
                "zeta",
                installed=InstalledInfo(installed=True, version="1.0.0"),
                latest=LatestInfo(checked=True, version="1.0.0", source="index"),
            ),
            _entry(
                "alpha",
                installed=InstalledInfo(installed=True, version="1.0.0"),
                latest=LatestInfo(checked=True, version="1.1.0", source="index"),
            ),
            _entry(
                "beta",
                installed=InstalledInfo(installed=True, version="1.0.0"),
                latest=LatestInfo(checked=True, version="1.1.0", source="index"),
            ),
        ),
        from_cache=True,
        stale=False,
    )
    rows = build_update_rows(_load_result(catalog=catalog), uv_tool=None, offline=False)
    grouped = select_rows(rows, needle="")
    builtin = next(
        section for header, _style, section in grouped if "Built-in" in header
    )
    assert [row.label for row in builtin] == ["alpha", "beta", "zeta"]


def test_select_rows_one_needle_matches_all_domains() -> None:
    core = CorePackageVersion(
        name="sase",
        distribution_name="needle-dist",
        installed_version="1.0.0",
        latest_version="1.0.0",
        latest_checked=True,
        update_available=False,
    )
    plugin = _entry("github", topics=("needle-dist",))
    status = AgentCliStatus(
        name="claude",
        display_name="Claude Code",
        binary="needle-dist",
        executable="/bin/claude",
        installed_version="1.0.0",
        latest_version="1.0.0",
        install_method=InstallMethod.SELF_MANAGED,
        update_available=False,
        docs_url=None,
        install_hint="install",
        self_update_argv=("update",),
    )
    rows = build_update_rows(
        _load_result(
            core_versions=CoreVersions(packages=(core,)),
            catalog=PluginCatalog(
                fetched_at=_NOW, entries=(plugin,), from_cache=True, stale=False
            ),
            agent_cli_statuses=(status,),
        ),
        uv_tool=None,
        offline=False,
        plan_fn=plan_agent_cli_updates,
    )
    grouped = select_rows(rows, needle="needle-dist")
    keys = [row.key for _header, _style, section in grouped for row in section]
    assert keys == ["core:sase", "plugin:github", "cli:claude"]


def test_select_rows_returns_installed_and_not_installed_rows() -> None:
    catalog = PluginCatalog(
        fetched_at=_NOW,
        entries=(
            _entry(
                "github",
                installed=InstalledInfo(installed=True, version="1.0.0"),
                latest=LatestInfo(checked=True, version="1.1.0", source="index"),
            ),
            _entry("nvim"),
        ),
        from_cache=True,
        stale=False,
    )
    rows = build_update_rows(
        _load_result(
            catalog=catalog,
            agent_cli_statuses=(_not_installed_cli_status(),),
        ),
        uv_tool=None,
        offline=False,
    )
    grouped = select_rows(rows, needle="")
    keys = [row.key for _header, _style, section in grouped for row in section]
    assert "plugin:nvim" in keys
    assert "cli:qwen" in keys
    assert "plugin:github" in keys
    builtin = next(
        section for header, _style, section in grouped if "Built-in" in header
    )
    assert [row.key for row in builtin][0] == "plugin:github"


# -- agent-CLI install capability, badge, and label per route ------------------


def test_agent_cli_install_capability_badge_and_label_per_route() -> None:
    npm_row = _cli_row(_installable_cli_status(route="npm"))
    assert "install" in npm_row.capabilities
    assert npm_row.source == "npm"
    assert npm_row.version_label == "latest v0.8.0"

    script_row = _cli_row(_installable_cli_status(route="script"))
    assert "install" in script_row.capabilities
    assert script_row.source == "script"
    assert script_row.version_label == "latest v0.8.0"

    manual_row = _cli_row(_installable_cli_status(route="manual"))
    assert "install" not in manual_row.capabilities
    assert manual_row.source == "manual"
    assert manual_row.version_label == "latest v0.8.0"

    bundled_row = _cli_row(_installable_cli_status(route="bundled"))
    assert "install" not in bundled_row.capabilities
    assert bundled_row.source == "bundled"


def test_agent_cli_installed_rows_keep_install_method_badge() -> None:
    row = _cli_row(_ready_cli_status())
    assert "install" not in row.capabilities
    assert row.source == "self_managed"


def test_agent_cli_install_never_coexists_with_mark_update() -> None:
    for route in ("npm", "script", "manual", "bundled"):
        row = _cli_row(_installable_cli_status(route=route))
        assert not ({"install", "mark_update"} <= row.capabilities)


def test_agent_cli_haystack_covers_install_route_and_package() -> None:
    row = _cli_row(_installable_cli_status(route="npm"))
    assert "not installed" in row.haystack
    assert "npm" in row.haystack
    assert "@qwen-code/qwen-code" in row.haystack

    manual_row = _cli_row(_installable_cli_status(route="manual"))
    assert "manual" in manual_row.haystack


def test_not_installed_plugin_row_is_uninstalled() -> None:
    nvim = build_plugin_row(_entry("nvim"), blocked=False)
    assert nvim.installed is False
