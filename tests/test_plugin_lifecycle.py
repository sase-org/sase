"""Command-aware plugin install, update, and uninstall (phase sase-1if.5).

Covers the lifecycle contract: inventory groups, command names in the
installed index, before/after command diffs around every plugin mutation, a
fresh-child completion refresh only when the command set changed, announced
commands in CLI result panels and JSON, and a non-fatal refresh failure.
"""

from __future__ import annotations

import argparse
import io
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from rich.console import Console

from sase.completion.install_models import (
    CompletionRefreshReport,
    RefreshShellOutcome,
)
from sase.plugin_commands.snapshot import (
    CommandChange,
    CommandChanges,
    CommandSnapshotEntry,
    diff_command_snapshots,
)
from sase.plugins import cli_install, cli_uninstall, cli_update
from sase.plugins.catalog import PluginCatalogEntry
from sase.plugins.cli_install import handle_plugin_install_command
from sase.plugins.cli_uninstall import handle_plugin_uninstall_command
from sase.plugins.cli_update import handle_plugin_update_command
from sase.plugins.installed import InstalledInfo, build_installed_index
from sase.plugins.inventory import (
    ENTRY_POINT_GROUPS,
    PROVIDER_ENTRY_POINT_GROUPS,
)
from sase.plugins.json_payload import plugin_entry_json
from sase.plugins.operations import (
    InstallReady,
    UpdateReady,
    UninstallReady,
    execute_install,
    execute_uninstall,
    execute_update,
    plan_install,
    plan_uninstall,
    plan_update,
)
from sase.plugins.render_results import (
    render_install_result,
    render_plugin_uninstall_result,
    render_plugin_update_result,
)
from sase.uv_tool.runner import UvChangeSet, parse_uv_output
from sase.version._plugins import plugin_candidates_from_distributions

from ._plugin_operations_helpers import (
    _INSTALL_OUTPUT,
    _UPGRADE_OUTPUT,
    _all_available,
    _catalog,
    _install,
)


def _entry(
    name: str, dist: str, version: str, location: str = ""
) -> CommandSnapshotEntry:
    return CommandSnapshotEntry(
        name=name, distribution=dist, version=version, location=location
    )


def _console() -> Console:
    return Console(file=io.StringIO(), width=200, no_color=True)


def _text(console: Console) -> str:
    return console.file.getvalue()  # type: ignore[attr-defined]


def _ok_report(*shells: str) -> CompletionRefreshReport:
    return CompletionRefreshReport(
        attempted=True,
        outcomes=tuple(
            RefreshShellOutcome(shell=shell, ok=True, detail="refreshed", target=None)
            for shell in shells
        ),
    )


# --------------------------------------------------------------------------- #
# Snapshot diffs
# --------------------------------------------------------------------------- #


def test_diff_empty_snapshots_is_falsy() -> None:
    changes = diff_command_snapshots({}, {})
    assert not changes
    assert changes.to_json() == {"added": [], "removed": [], "updated": []}


def test_diff_reports_added_removed_and_updated() -> None:
    before = {
        "listen": _entry("listen", "sase-listen", "0.1.1"),
        "gone": _entry("gone", "sase-gone", "1.0.0"),
        "same": _entry("same", "sase-same", "2.0.0"),
    }
    after = {
        "listen": _entry("listen", "sase-listen", "0.1.2"),
        "new": _entry("new", "sase-new", "0.0.1"),
        "same": _entry("same", "sase-same", "2.0.0"),
    }
    changes = diff_command_snapshots(before, after)
    assert changes
    assert changes.added == (
        CommandChange(name="new", distribution="sase-new", version="0.0.1"),
    )
    assert changes.removed == (
        CommandChange(name="gone", distribution="sase-gone", version="1.0.0"),
    )
    assert changes.updated == (
        CommandChange(name="listen", distribution="sase-listen", version="0.1.2"),
    )
    assert changes.to_json() == {
        "added": [
            {"name": "new", "distribution": "sase-new", "version": "0.0.1"},
        ],
        "removed": [
            {"name": "gone", "distribution": "sase-gone", "version": "1.0.0"},
        ],
        "updated": [
            {"name": "listen", "distribution": "sase-listen", "version": "0.1.2"},
        ],
    }


# --------------------------------------------------------------------------- #
# Inventory and installed index
# --------------------------------------------------------------------------- #


def test_inventory_groups_cover_commands_macros_and_pager_history() -> None:
    from sase.legacy_xprompt_syntax import RETIRED_PLUGIN_GROUP

    assert "sase_commands" in ENTRY_POINT_GROUPS
    assert "sase_macros" in ENTRY_POINT_GROUPS
    assert "sase_pager_history" in ENTRY_POINT_GROUPS
    assert "sase_commands" in PROVIDER_ENTRY_POINT_GROUPS
    # The retired group is a recognition signal only, never a capability.
    assert RETIRED_PLUGIN_GROUP not in ENTRY_POINT_GROUPS
    assert RETIRED_PLUGIN_GROUP not in PROVIDER_ENTRY_POINT_GROUPS


def test_retired_group_distributions_are_still_detected(tmp_path: Path) -> None:
    from sase.legacy_xprompt_syntax import RETIRED_PLUGIN_GROUP
    from tests._version_inventory_helpers import (
        _FakeDistribution,
        _FakeEntryPoint,
    )

    entry_point = _FakeEntryPoint(
        group=RETIRED_PLUGIN_GROUP,
        name="prompts",
        value="sase_legacy.resources",
    )
    dist = _FakeDistribution(
        name="sase-legacy-only",
        version="1.0.0",
        location=tmp_path,
        entry_points=(entry_point,),
    )
    candidates = plugin_candidates_from_distributions([dist])
    assert [candidate.distribution_name for candidate in candidates] == [
        "sase-legacy-only"
    ]
    assert candidates[0].plugin_signals == (
        "distribution_name:sase-legacy-only",
        f"entry_point:{RETIRED_PLUGIN_GROUP}:prompts=sase_legacy.resources",
    )
    assert entry_point.load_calls == 0


def test_installed_index_carries_command_names() -> None:
    inventory = SimpleNamespace(
        distributions=(
            SimpleNamespace(
                package="sase-listen",
                version="0.1.2",
                entry_points=(
                    "sase_commands:listen",
                    "sase_config:sase_listen",
                ),
            ),
            SimpleNamespace(
                package="sase-github",
                version="0.4.0",
                entry_points=("sase_vcs:github",),
            ),
        )
    )
    index = build_installed_index(
        inventory_fn=lambda *, load_resource_entry_points: inventory,
        candidates_fn=lambda: (),
        receipt_plugins_fn=lambda: (),
    )
    assert index["sase-listen"].commands == ("listen",)
    assert index["sase-listen"].entry_point_groups == (
        "sase_commands",
        "sase_config",
    )
    assert index["sase-github"].commands == ()


def test_plugin_entry_json_includes_commands() -> None:
    entry = PluginCatalogEntry(
        name="listen",
        repo="sase-listen",
        full_name="sase-org/sase-listen",
        owner="sase-org",
        description="desc",
        url="https://github.com/sase-org/sase-listen",
        homepage="",
        topics=("sase--plugin",),
        stars=0,
        archived=False,
        license="MIT",
        updated_at="",
        installed=InstalledInfo(
            installed=True,
            version="0.1.2",
            entry_point_groups=("sase_commands",),
            commands=("listen",),
        ),
    )
    payload = plugin_entry_json(entry)
    assert payload["installed"] == {
        "installed": True,
        "version": "0.1.2",
        "entry_point_groups": ["sase_commands"],
        "commands": ["listen"],
    }


# --------------------------------------------------------------------------- #
# Executors: diffs and refresh behavior
# --------------------------------------------------------------------------- #


def _snapshots(*states: dict[str, CommandSnapshotEntry]):
    snapshots = iter(states)
    return lambda: next(snapshots)


def test_execute_install_reports_added_command_and_refreshes(tmp_path: Path) -> None:
    before: dict[str, CommandSnapshotEntry] = {}
    after = {"listen": _entry("listen", "sase-listen", "0.1.2")}
    refresh_calls: list[Any] = []

    def _refresh(install: Any) -> CompletionRefreshReport:
        refresh_calls.append(install)
        return _ok_report("zsh")

    plan = plan_install(
        "github",
        load_fn=lambda *, refresh: _catalog(),
        probe_fn=lambda: _install(tmp_path),
        availability_fn=_all_available,
    )
    assert isinstance(plan, InstallReady)
    outcome = execute_install(
        plan,
        run_fn=lambda _argv: parse_uv_output(_INSTALL_OUTPUT),
        installed_index_fn=lambda: {},
        clock=lambda: 0.0,
        snapshot_fn=_snapshots(before, after),
        probe_fn=lambda: _install(tmp_path),
        refresh_fn=_refresh,
    )
    assert [change.name for change in outcome.effects.command_changes.added] == [
        "listen"
    ]
    assert outcome.effects.completion_refresh.attempted is True
    assert len(refresh_calls) == 1


def test_no_refresh_when_command_set_is_unchanged(tmp_path: Path) -> None:
    state = {"listen": _entry("listen", "sase-listen", "0.1.2")}

    def _boom(install: Any) -> CompletionRefreshReport:
        raise AssertionError("refresh must not run when nothing changed")

    plan = plan_install(
        "github",
        load_fn=lambda *, refresh: _catalog(),
        probe_fn=lambda: _install(tmp_path),
        availability_fn=_all_available,
    )
    assert isinstance(plan, InstallReady)
    outcome = execute_install(
        plan,
        run_fn=lambda _argv: parse_uv_output(_INSTALL_OUTPUT),
        installed_index_fn=lambda: {},
        clock=lambda: 0.0,
        snapshot_fn=_snapshots(dict(state), dict(state)),
        probe_fn=lambda: _install(tmp_path),
        refresh_fn=_boom,
    )
    assert not outcome.effects.command_changes
    assert outcome.effects.completion_refresh.attempted is False


def test_refresh_failure_is_nonfatal(tmp_path: Path) -> None:
    before: dict[str, CommandSnapshotEntry] = {}
    after = {"listen": _entry("listen", "sase-listen", "0.1.2")}

    def _fail(install: Any) -> CompletionRefreshReport:
        raise RuntimeError("child exploded")

    plan = plan_install(
        "github",
        load_fn=lambda *, refresh: _catalog(),
        probe_fn=lambda: _install(tmp_path),
        availability_fn=_all_available,
    )
    assert isinstance(plan, InstallReady)
    outcome = execute_install(
        plan,
        run_fn=lambda _argv: parse_uv_output(_INSTALL_OUTPUT),
        installed_index_fn=lambda: {},
        clock=lambda: 0.0,
        snapshot_fn=_snapshots(before, after),
        probe_fn=lambda: _install(tmp_path),
        refresh_fn=_fail,
    )
    # The mutation still succeeds; the failure is reported with a retry hint.
    assert [change.name for change in outcome.effects.command_changes.added] == [
        "listen"
    ]
    report = outcome.effects.completion_refresh
    assert report.attempted is True
    assert all(not outcome.ok for outcome in report.outcomes)
    assert "sase completion refresh" in report.outcomes[0].detail


def test_execute_update_and_uninstall_carry_effects(tmp_path: Path) -> None:
    from ._plugin_operations_helpers import _UPDATE_RECEIPT

    before = {"listen": _entry("listen", "sase-listen", "0.1.1")}
    after = {"listen": _entry("listen", "sase-listen", "0.1.2")}

    update_plan = plan_update(
        "github",
        load_fn=lambda *, refresh: _catalog(),
        probe_fn=lambda: _install(tmp_path, _UPDATE_RECEIPT),
    )
    assert isinstance(update_plan, UpdateReady)
    update_outcome = execute_update(
        update_plan,
        run_fn=lambda _argv: parse_uv_output(_UPGRADE_OUTPUT),
        clock=lambda: 0.0,
        snapshot_fn=_snapshots(before, after),
        probe_fn=lambda: _install(tmp_path),
        refresh_fn=lambda _install: _ok_report("bash"),
    )
    assert [
        change.name for change in update_outcome.effects.command_changes.updated
    ] == ["listen"]
    assert update_outcome.effects.completion_refresh.attempted is True

    uninstall_plan = plan_uninstall(
        "github",
        load_fn=lambda *, refresh: _catalog(),
        probe_fn=lambda: _install(tmp_path, _UPDATE_RECEIPT),
    )
    assert isinstance(uninstall_plan, UninstallReady)
    uninstall_outcome = execute_uninstall(
        uninstall_plan,
        run_fn=lambda _argv: UvChangeSet(),
        clock=lambda: 0.0,
        snapshot_fn=_snapshots(dict(after), {}),
        probe_fn=lambda: _install(tmp_path),
        refresh_fn=lambda _install: _ok_report("fish"),
    )
    assert [
        change.name for change in uninstall_outcome.effects.command_changes.removed
    ] == ["listen"]
    assert uninstall_outcome.effects.completion_refresh.attempted is True


# --------------------------------------------------------------------------- #
# Panels and JSON
# --------------------------------------------------------------------------- #


def test_install_panel_announces_new_command_and_refresh() -> None:
    out = _console()
    render_install_result(
        dist_name="sase-listen",
        short_name="listen",
        change_set=parse_uv_output(
            "Resolved 1 package in 10ms\n + sase-listen==0.1.2\n"
        ),
        groups=("sase_commands",),
        elapsed=1.0,
        console=out,
        command_changes=CommandChanges(
            added=(
                CommandChange(
                    name="listen", distribution="sase-listen", version="0.1.2"
                ),
            )
        ),
        completion_refresh=_ok_report("zsh"),
    )
    text = _text(out)
    assert "❯ sase listen" in text
    assert "new command" in text
    assert "Try it:" in text and "sase listen --help" in text
    assert "Shell completion refreshed (zsh)" in text
    assert "exec $SHELL" in text


def test_uninstall_panel_announces_removed_command() -> None:
    out = _console()
    render_plugin_uninstall_result(
        change_set=UvChangeSet(),
        dist_name="sase-listen",
        short_name="listen",
        elapsed=1.0,
        console=out,
        command_changes=CommandChanges(
            removed=(
                CommandChange(
                    name="listen", distribution="sase-listen", version="0.1.2"
                ),
            )
        ),
        completion_refresh=CompletionRefreshReport(attempted=False, outcomes=()),
    )
    text = _text(out)
    assert "❯ sase listen" in text
    assert "command removed" in text
    assert "Shell completion refreshed" not in text


def test_update_panel_hides_provider_only_updates() -> None:
    out = _console()
    render_plugin_update_result(
        change_set=parse_uv_output(_UPGRADE_OUTPUT),
        dist_names=("sase-github",),
        elapsed=1.0,
        console=out,
        command_changes=CommandChanges(
            updated=(
                CommandChange(
                    name="listen", distribution="sase-listen", version="0.1.2"
                ),
            )
        ),
        completion_refresh=_ok_report("zsh"),
    )
    text = _text(out)
    assert "❯ sase listen" not in text
    assert "Shell completion refreshed (zsh)" in text


def test_install_json_carries_command_changes_and_refresh(
    tmp_path: Path, capsys: Any
) -> None:
    after = {"listen": _entry("listen", "sase-listen", "0.1.2")}
    code = handle_plugin_install_command(
        argparse.Namespace(
            plugin_subcommand="install",
            plugin="github",
            git=False,
            refresh=False,
            dry_run=False,
            json=True,
        ),
        load_fn=lambda *, refresh: _catalog(),
        probe_fn=lambda: _install(tmp_path),
        availability_fn=_all_available,
        run_fn=lambda _argv: parse_uv_output(_INSTALL_OUTPUT),
        installed_index_fn=lambda: {},
        scheduler_running_fn=lambda: False,
        clock=lambda: 0.0,
        snapshot_fn=_snapshots({}, after),
        refresh_fn=lambda _install: _ok_report("zsh"),
    )
    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["command_changes"] == {
        "added": [
            {"name": "listen", "distribution": "sase-listen", "version": "0.1.2"}
        ],
        "removed": [],
        "updated": [],
    }
    assert payload["completion_refresh"]["attempted"] is True
    assert payload["completion_refresh"]["shells"][0]["shell"] == "zsh"


def test_update_and_uninstall_json_carry_effect_shapes(
    tmp_path: Path, capsys: Any
) -> None:
    from ._plugin_operations_helpers import _UPDATE_RECEIPT

    before = {"listen": _entry("listen", "sase-listen", "0.1.1")}
    after = {"listen": _entry("listen", "sase-listen", "0.1.2")}
    code = handle_plugin_update_command(
        argparse.Namespace(
            plugin_subcommand="update",
            plugin="github",
            all=False,
            refresh=False,
            dry_run=False,
            json=True,
        ),
        load_fn=lambda *, refresh: _catalog(),
        probe_fn=lambda: _install(tmp_path, _UPDATE_RECEIPT),
        run_fn=lambda _argv: parse_uv_output(_UPGRADE_OUTPUT),
        scheduler_running_fn=lambda: False,
        clock=lambda: 0.0,
        snapshot_fn=_snapshots(before, after),
        refresh_fn=lambda _install: _ok_report("bash"),
    )
    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["command_changes"]["updated"] == [
        {"name": "listen", "distribution": "sase-listen", "version": "0.1.2"}
    ]
    assert payload["completion_refresh"]["attempted"] is True

    code = handle_plugin_uninstall_command(
        argparse.Namespace(
            plugin_subcommand="uninstall",
            plugin="github",
            refresh=False,
            dry_run=False,
            json=True,
        ),
        load_fn=lambda *, refresh: _catalog(),
        probe_fn=lambda: _install(tmp_path, _UPDATE_RECEIPT),
        run_fn=lambda _argv: UvChangeSet(),
        scheduler_running_fn=lambda: False,
        clock=lambda: 0.0,
        snapshot_fn=_snapshots(dict(after), {}),
        refresh_fn=lambda _install: _ok_report("fish"),
    )
    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["command_changes"]["removed"] == [
        {"name": "listen", "distribution": "sase-listen", "version": "0.1.2"}
    ]
    assert payload["completion_refresh"]["attempted"] is True


def test_plugin_list_groups_cell_shows_command_chip() -> None:
    from sase.plugins.catalog import PluginCatalogEntry
    from sase.plugins.render_catalog import _groups_cell

    entry = PluginCatalogEntry(
        name="listen",
        repo="sase-listen",
        full_name="sase-org/sase-listen",
        owner="sase-org",
        description="desc",
        url="https://github.com/sase-org/sase-listen",
        homepage="",
        topics=("sase--plugin",),
        stars=0,
        archived=False,
        license="MIT",
        updated_at="",
        installed=InstalledInfo(
            installed=True,
            version="0.1.2",
            entry_point_groups=("sase_commands",),
            commands=("listen",),
        ),
    )
    cell = _groups_cell(entry)
    assert "❯ sase listen" in cell.plain
    assert "sase_commands" in cell.plain
