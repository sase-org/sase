"""Pure, widget-free tests for the merged Updates-tab row model."""

from __future__ import annotations

from pathlib import Path

from sase.ace.tui.modals.plugins_browser_loading import PluginsLoadResult
from sase.ace.tui.modals.plugins_browser_rows import (
    _core_version_label,
    _agent_cli_version_label,
    _plugin_version_label,
    build_plugin_row,
    build_update_rows,
    dev_state_label,
    _row_in_scope,
    scope_counts,
    select_rows,
)
from sase.agent_clis.models import (
    AgentCliStatus,
    AgentCliUnknownName,
    InstallMethod,
)
from sase.agent_clis.operations import plan_agent_cli_updates
from sase.plugins.catalog import PluginCatalog, PluginCatalogEntry
from sase.plugins.installed import InstalledInfo
from sase.plugins.latest import LatestInfo
from sase.uv_tool.detect import NotUvToolInstall, NotUvToolReason
from sase.uv_tool.versions import CorePackageVersion, CoreVersions

_NOW = 1_700_000_000.0


def _entry(
    name: str,
    *,
    owner: str = "sase-org",
    installed: InstalledInfo | None = None,
    latest: LatestInfo | None = None,
    description: str = "A plugin.",
    topics: tuple[str, ...] = ("sase--plugin",),
) -> PluginCatalogEntry:
    repo = f"sase-{name}"
    return PluginCatalogEntry(
        name=name,
        repo=repo,
        full_name=f"{owner}/{repo}",
        owner=owner,
        description=description,
        url=f"https://github.com/{owner}/{repo}",
        homepage="",
        topics=topics,
        stars=3,
        archived=False,
        license="MIT",
        updated_at="2026-06-01",
        installed=installed or InstalledInfo.not_installed(),
        latest=latest or LatestInfo.unknown(),
    )


def _core_package(
    *,
    name: str = "sase",
    installed_version: str | None = "1.0.0",
    latest_version: str | None = "1.0.0",
    latest_checked: bool = True,
    latest_error: str | None = None,
    install_type: str | None = None,
) -> CorePackageVersion:
    return CorePackageVersion(
        name=name,
        distribution_name=name,
        installed_version=installed_version,
        latest_version=latest_version,
        latest_checked=latest_checked,
        update_available=bool(
            latest_checked
            and installed_version
            and latest_version
            and latest_version != installed_version
        ),
        latest_error=latest_error,
        install_type=install_type,
    )


def _ready_cli_status(
    *,
    update_available: bool = True,
) -> AgentCliStatus:
    """A self-managed CLI with a safe, ready update command."""
    return AgentCliStatus(
        name="claude",
        display_name="Claude Code",
        binary="claude",
        executable="/home/dev/.local/bin/claude",
        installed_version="1.0.0",
        latest_version="1.1.0",
        install_method=InstallMethod.SELF_MANAGED,
        update_available=update_available,
        docs_url="https://code.claude.com/docs/en/setup",
        install_hint="Install Claude Code from vendor docs",
        self_update_argv=("update",),
    )


def _manual_only_cli_status() -> AgentCliStatus:
    """A Homebrew-managed CLI: manual-only, but genuinely outdated."""
    return AgentCliStatus(
        name="codex",
        display_name="Codex CLI",
        binary="codex",
        executable="/usr/local/bin/codex",
        installed_version="0.9.0",
        latest_version="1.0.0",
        install_method=InstallMethod.HOMEBREW,
        update_available=True,
        docs_url="https://developers.openai.com/codex/cli",
        install_hint="npm install -g @openai/codex",
        brew_package="codex",
    )


def _not_installed_cli_status() -> AgentCliStatus:
    return AgentCliStatus(
        name="qwen",
        display_name="Qwen Code",
        binary="qwen",
        executable=None,
        installed_version=None,
        latest_version="0.8.0",
        install_method=InstallMethod.NOT_INSTALLED,
        update_available=False,
        docs_url="https://github.com/QwenLM/qwen-code",
        install_hint="npm install -g @qwen-code/qwen-code",
    )


def _not_uv_tool() -> NotUvToolInstall:
    return NotUvToolInstall(
        reason=NotUvToolReason.WRONG_PREFIX,
        sys_prefix=Path("/home/dev/project/.venv"),
        expected_sase_dir=Path("/home/dev/.local/share/uv/tools/sase"),
        receipt_path=Path("/home/dev/.local/share/uv/tools/sase/uv-receipt.toml"),
        uv_path="/usr/bin/uv",
    )


def _load_result(
    *,
    core_versions: CoreVersions | None = None,
    catalog: PluginCatalog | None = None,
    agent_cli_statuses: tuple[AgentCliStatus, ...] = (),
    agent_cli_colors: dict[str, str] | None = None,
) -> PluginsLoadResult:
    return PluginsLoadResult(
        catalog=catalog,
        error=None,
        now=_NOW,
        core_versions=core_versions,
        agent_cli_statuses=agent_cli_statuses,
        agent_cli_colors=agent_cli_colors or {},
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


# -- version_label parity with today's renderers -------------------------------


def test_plugin_version_label_installed_with_update() -> None:
    entry = _entry(
        "github",
        installed=InstalledInfo(installed=True, version="1.0.0"),
        latest=LatestInfo(checked=True, version="1.1.0", source="index"),
    )
    assert _plugin_version_label(entry) == "v1.0.0 → v1.1.0"


def test_plugin_version_label_installed_no_update() -> None:
    entry = _entry(
        "telegram",
        installed=InstalledInfo(installed=True, version="0.5.0"),
        latest=LatestInfo(checked=True, version="0.5.0", source="index"),
    )
    assert _plugin_version_label(entry) == "v0.5.0"


def test_plugin_version_label_not_installed_with_latest() -> None:
    entry = _entry(
        "nvim", latest=LatestInfo(checked=True, version="2.0.0", source="index")
    )
    assert _plugin_version_label(entry) == "latest v2.0.0"


def test_plugin_version_label_not_installed_unknown() -> None:
    assert _plugin_version_label(_entry("nvim")) == ""


def test_plugin_version_label_git_source() -> None:
    entry = _entry(
        "github",
        installed=InstalledInfo(installed=True, version="1.0.0"),
        latest=LatestInfo(checked=True, source="git"),
    )
    assert _plugin_version_label(entry) == "git"


def test_plugin_version_label_editable_with_update() -> None:
    entry = _entry(
        "github",
        installed=InstalledInfo(installed=True, version="1.0.0"),
        latest=LatestInfo(
            checked=True,
            source="editable",
            current_version="1.0.0",
            version="1.1.0",
            update_available=True,
        ),
    )
    assert _plugin_version_label(entry) == "v1.0.0 → v1.1.0  dev"


def test_plugin_version_label_editable_current_state() -> None:
    entry = _entry(
        "github",
        installed=InstalledInfo(installed=True, version="1.0.0"),
        latest=LatestInfo(
            checked=True,
            source="editable",
            current_version="1.0.0",
            state="dirty",
        ),
    )
    assert _plugin_version_label(entry) == "v1.0.0  dev · local changes"


def test_dev_state_label_known_and_unknown_states() -> None:
    assert dev_state_label("dirty") == "local changes"
    assert dev_state_label("current") == ""
    assert dev_state_label(None) == ""
    assert dev_state_label("mystery") == "mystery"


def test_agent_cli_version_label_variants() -> None:
    assert _agent_cli_version_label(_ready_cli_status()) == "v1.0.0 → v1.1.0"
    assert (
        _agent_cli_version_label(_ready_cli_status(update_available=False)) == "v1.0.0"
    )
    assert _agent_cli_version_label(_not_installed_cli_status()) == "not installed"


def test_core_version_label_variants() -> None:
    assert (
        _core_version_label(
            _core_package(installed_version="1.0.0", latest_version="1.1.0")
        )
        == "v1.0.0 → v1.1.0"
    )
    assert (
        _core_version_label(
            _core_package(installed_version="1.0.0", latest_version="1.0.0")
        )
        == "v1.0.0"
    )
    assert (
        _core_version_label(_core_package(installed_version=None, latest_version=None))
        == "not installed"
    )
    assert (
        _core_version_label(
            _core_package(
                installed_version="1.0.0",
                latest_version="1.0.0",
                install_type="editable",
            )
        )
        == "v1.0.0   dev"
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
    grouped = select_rows(rows, scope="all", needle="")
    assert [header for header, _style, _rows in grouped] == [
        "── SASE ──",
        "── Plugins · Built-in ──",
        "── Plugins · Community ──",
        "── Agent CLIs ──",
    ]
    keys = [row.key for _header, _style, section in grouped for row in section]
    assert keys == ["core:sase", "plugin:github", "plugin:acme", "cli:claude"]


def test_row_in_scope_outdated_installed_and_all() -> None:
    manual = build_update_rows(
        _load_result(agent_cli_statuses=(_manual_only_cli_status(),)),
        uv_tool=None,
        offline=False,
        plan_fn=plan_agent_cli_updates,
    )[0]
    assert _row_in_scope(manual, "outdated") is True
    assert _row_in_scope(manual, "installed") is True

    error_row = build_update_rows(
        _load_result(
            core_versions=CoreVersions(
                packages=(_core_package(latest_error="pypi unreachable"),)
            )
        ),
        uv_tool=None,
        offline=False,
    )[0]
    assert error_row.update_available is False
    assert error_row.error == "pypi unreachable"
    assert _row_in_scope(error_row, "outdated") is True

    nvim = build_plugin_row(_entry("nvim"), blocked=False)
    assert nvim.installed is False
    assert _row_in_scope(nvim, "installed") is False
    assert _row_in_scope(nvim, "all") is True


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
    grouped = select_rows(rows, scope="all", needle="")
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
    grouped = select_rows(rows, scope="all", needle="needle-dist")
    keys = [row.key for _header, _style, section in grouped for row in section]
    assert keys == ["core:sase", "plugin:github", "cli:claude"]


def test_scope_counts_ignore_filter_and_count_each_row_once() -> None:
    nvim = build_plugin_row(_entry("nvim"), blocked=False)
    github = build_plugin_row(
        _entry(
            "github",
            installed=InstalledInfo(installed=True, version="1.0.0"),
            latest=LatestInfo(checked=True, version="1.1.0", source="index"),
        ),
        blocked=False,
    )
    counts = scope_counts((nvim, github))
    assert counts["all"] == 2
    assert counts["installed"] == 1
    assert counts["outdated"] == 1
