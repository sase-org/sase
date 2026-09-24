"""Shared factories for plugins-browser row-model tests."""

from __future__ import annotations

from pathlib import Path

from sase.ace.tui.modals.plugins_browser_loading import PluginsLoadResult
from sase.ace.tui.modals.plugins_browser_rows import build_update_rows
from sase.agent_clis.models import (
    AgentCliStatus,
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


def _installable_cli_status(*, route: str) -> AgentCliStatus:
    base = _not_installed_cli_status().__dict__
    if route == "npm":
        return AgentCliStatus(
            **{
                **base,
                "install_manager": "npm",
                "package": "@qwen-code/qwen-code",
            }
        )
    if route == "script":
        return AgentCliStatus(
            **{
                **base,
                "install_manager": InstallMethod.SCRIPT,
                "install_script_url": "https://dev.meta.ai/install.sh",
            }
        )
    if route == "bundled":
        return AgentCliStatus(**{**base, "install_manager": InstallMethod.BUNDLED})
    return AgentCliStatus(**{**base, "install_manager": "native"})


def _cli_row(status: AgentCliStatus):  # -> UpdateRow
    rows = build_update_rows(
        _load_result(agent_cli_statuses=(status,)),
        uv_tool=None,
        offline=False,
        plan_fn=plan_agent_cli_updates,
    )
    assert len(rows) == 1
    return rows[0]
