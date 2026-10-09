"""Updates-tab command surfaces for epic sase-1if phase sase-1if.7.

Covers the shared detail-panel Commands row, the Updates row chip, the
lazy declared-preview worker, the install/uninstall/update confirm-modal
command lines, the v4 receipt codec, the lifecycle-effects receipt builders,
and the post-update toast command lines.
"""

from __future__ import annotations

import io
from types import SimpleNamespace
from typing import Any

from rich.console import Console
from rich.text import Text

from sase.ace import update_receipt
from sase.ace._update_receipt_codec import receipt_from_json, receipt_to_json
from sase.ace.tui.actions import post_update_toast
from sase.ace.tui.modals.plugin_action_confirm_modal import PluginActionVariant
from sase.ace.tui.modals.plugins_browser_declared import (
    PluginsBrowserDeclaredMixin,
)
from sase.ace.tui.modals.plugins_browser_install_previews import (
    install_command_details,
    install_command_warnings,
    install_many_item_suffix,
)
from sase.ace.tui.modals.plugins_browser_rendering import (
    PluginsBrowserRenderingMixin,
)
from sase.ace.tui.modals.plugins_browser_rows import build_plugin_row
from sase.ace.tui.modals.plugins_browser_uninstall import (
    _uninstall_command_details,
)
from sase.ace.tui.modals.plugins_browser_update import _update_command_details
from sase.ace.update_receipt import (
    UpdateToastReceipt,
    UpdateVersionTransition,
    build_update_receipt,
)
from sase.completion.install_models import CompletionRefreshReport
from sase.plugin_commands.snapshot import (
    CommandChanges,
    _CommandChange,
)
from sase.plugins.catalog import PluginCatalogEntry
from sase.plugins.declared_commands import (
    DeclaredCommandProblem,
    DeclaredCommands,
    declared_cache_key,
)
from sase.plugins.installed import InstalledInfo
from sase.plugins.operations import (
    InstallOutcome,
    InstallReady,
    ResolvedSpec,
)
from sase.plugins.post_change import PluginChangeEffects
from sase.plugins.render import build_detail_panel
from sase.uv_tool.receipt import Requirement
from sase.uv_tool.runner import ChangeKind, UvChangeSet, UvPackageChange


def _entry(
    name: str = "listen",
    *,
    installed: bool = False,
    commands: tuple[str, ...] = (),
) -> PluginCatalogEntry:
    return PluginCatalogEntry(
        name=name,
        repo="sase-listen",
        full_name="sase-org/sase-listen",
        owner="sase-org",
        description="listen plugin",
        url="https://github.com/sase-org/sase-listen",
        homepage="",
        topics=("sase--plugin",),
        stars=7,
        archived=False,
        license="MIT",
        updated_at="2026-01-01",
        installed=InstalledInfo(
            installed=installed, version="1.0.0", commands=commands
        ),
    )


def _render(renderable: object) -> str:
    console = Console(file=io.StringIO(), width=200, no_color=True)
    console.print(renderable)
    return console.file.getvalue()  # type: ignore[attr-defined]


# --------------------------------------------------------------------------- #
# Detail panel Commands row
# --------------------------------------------------------------------------- #


def test_detail_panel_shows_installed_command_chip() -> None:
    text = _render(build_detail_panel(_entry(installed=True, commands=("listen",))))
    assert "Commands" in text
    assert "❯ sase listen" in text


def test_detail_panel_omits_commands_row_without_commands() -> None:
    text = _render(build_detail_panel(_entry(installed=True)))
    assert "Commands" not in text


def test_detail_panel_shows_declared_preview_dim() -> None:
    declared = DeclaredCommands(
        status="declared", names=("listen",), source="pyproject"
    )
    text = _render(build_detail_panel(_entry(), declared_commands=declared))
    assert "Commands" in text
    assert "❯ sase listen" in text
    assert "added on install" in text


def test_detail_panel_omits_commands_row_for_unknown_preview() -> None:
    assert "Commands" not in _render(build_detail_panel(_entry()))
    none = DeclaredCommands(status="none", names=(), source=None)
    assert "Commands" not in _render(
        build_detail_panel(_entry(), declared_commands=none)
    )


# --------------------------------------------------------------------------- #
# Updates row chip
# --------------------------------------------------------------------------- #


class _ChipHarness(PluginsBrowserRenderingMixin, PluginsBrowserDeclaredMixin):
    """Minimal pane stand-in for row-chip rendering."""

    def __init__(self) -> None:
        self._marked: set[str] = set()
        self._verbose = False
        self._plugin_declared_previews: dict[str, DeclaredCommands] = {}


def _row_text(harness: _ChipHarness, entry: PluginCatalogEntry) -> Text:
    return harness._row_text(build_plugin_row(entry, blocked=False))


def test_row_chip_bold_for_installed_commands() -> None:
    harness = _ChipHarness()
    text = _row_text(harness, _entry(installed=True, commands=("listen",)))
    offset = text.plain.index("❯ sase listen")
    covering = [span for span in text.spans if span.start <= offset < span.end]
    assert covering and all("bold" in str(span.style) for span in covering)


def test_row_chip_dim_for_cached_preview() -> None:
    harness = _ChipHarness()
    entry = _entry()
    harness._plugin_declared_previews[declared_cache_key(entry.full_name)] = (
        DeclaredCommands(status="declared", names=("listen",), source="pyproject")
    )
    text = _row_text(harness, entry)
    assert "❯ sase listen" in text.plain


def test_row_chip_absent_without_commands_or_preview() -> None:
    harness = _ChipHarness()
    assert "❯ sase" not in _row_text(harness, _entry()).plain
    assert "❯ sase" not in _row_text(harness, _entry(installed=True)).plain


# --------------------------------------------------------------------------- #
# Lazy declared-preview worker
# --------------------------------------------------------------------------- #


class _DeclaredHarness(PluginsBrowserDeclaredMixin):
    """Minimal pane stand-in for the declared-preview worker."""

    def __init__(self, entry: PluginCatalogEntry) -> None:
        self._offline = False
        self._plugin_declared_previews: dict[str, DeclaredCommands] = {}
        self._plugin_declared_loading: set[str] = set()
        self._plugin_declared_workers: dict[int, str] = {}
        self._catalog = SimpleNamespace(entries=(entry,))
        self._entry = entry
        self.spawned: list[dict[str, Any]] = []
        self.refreshed: list[str] = []
        self.rendered = 0

    def run_worker(self, task: Any, **kwargs: Any) -> Any:
        self.spawned.append(kwargs)
        worker = SimpleNamespace(task=task)
        self._worker_task = task
        return worker

    def _refresh_row(self, key: str) -> bool:
        self.refreshed.append(key)
        return True

    def _current_entry(self) -> PluginCatalogEntry | None:
        return self._entry

    def _render_detail_now(self, *, force: bool = False) -> None:
        self.rendered += 1


def test_declared_worker_settles_unknown_without_refetch() -> None:
    from textual.worker import WorkerState

    harness = _DeclaredHarness(_entry())
    harness._ensure_plugin_declared_preview(harness._entry)
    assert len(harness.spawned) == 1

    key = declared_cache_key(harness._entry.full_name)
    worker = SimpleNamespace(result=(key, DeclaredCommands(status="unknown")))
    event = SimpleNamespace(state=WorkerState.SUCCESS, worker=worker)
    harness._plugin_declared_workers[id(worker)] = key
    harness._on_plugin_declared_worker_state(event, key)

    harness._ensure_plugin_declared_preview(harness._entry)
    assert len(harness.spawned) == 1


def test_declared_worker_skips_installed_offline_and_loading() -> None:
    installed = _DeclaredHarness(_entry(installed=True, commands=("listen",)))
    installed._ensure_plugin_declared_preview(installed._entry)
    assert installed.spawned == []

    offline = _DeclaredHarness(_entry())
    offline._offline = True
    offline._ensure_plugin_declared_preview(offline._entry)
    assert offline.spawned == []

    loading = _DeclaredHarness(_entry())
    loading._plugin_declared_loading.add(declared_cache_key("sase-org/sase-listen"))
    loading._ensure_plugin_declared_preview(loading._entry)
    assert loading.spawned == []


def test_declared_worker_uses_own_group_and_refreshes_row() -> None:
    from textual.worker import WorkerState

    harness = _DeclaredHarness(_entry())
    harness._ensure_plugin_declared_preview(harness._entry)
    assert len(harness.spawned) == 1
    assert harness.spawned[0].get("group") == "updates-plugin-declared"

    declared = DeclaredCommands(
        status="declared", names=("listen",), source="pyproject"
    )
    key = declared_cache_key(harness._entry.full_name)
    worker = SimpleNamespace(result=(key, declared))
    event = SimpleNamespace(state=WorkerState.SUCCESS, worker=worker)
    harness._plugin_declared_workers[id(worker)] = key
    harness._on_plugin_declared_worker_state(event, key)

    assert harness._plugin_declared_previews[key] == declared
    assert harness.refreshed == ["plugin:listen"]
    assert harness.rendered == 1


# --------------------------------------------------------------------------- #
# Confirm-modal command lines
# --------------------------------------------------------------------------- #


def test_single_install_details_and_warnings() -> None:
    declared = DeclaredCommands(
        status="declared", names=("listen",), source="pyproject"
    )
    assert install_command_details(declared) == ("❯ Adds a new command: ❯ sase listen",)
    assert install_command_details(None) == ()
    assert install_command_details(DeclaredCommands(status="unknown")) == ()
    problems = (
        DeclaredCommandProblem(
            name="listen",
            kind="conflict",
            detail="sase listen would conflict with sase-listen — both would be disabled",
        ),
    )
    assert install_command_warnings(problems) == (problems[0].detail,)
    assert install_command_warnings(()) == ()


def test_batch_item_suffix() -> None:
    declared = DeclaredCommands(
        status="declared", names=("listen",), source="pyproject"
    )
    assert install_many_item_suffix(declared) == " (adds ❯ sase listen)"
    assert install_many_item_suffix(None) == ""
    assert install_many_item_suffix(DeclaredCommands(status="none")) == ""


def test_uninstall_details() -> None:
    assert _uninstall_command_details(("listen",)) == (
        "❯ Removes command: ❯ sase listen",
    )
    assert _uninstall_command_details(()) == ()


def test_update_details_only_when_preview_differs() -> None:
    declared = DeclaredCommands(
        status="declared", names=("listen",), source="pyproject"
    )
    assert _update_command_details((), declared) == ("❯ Adds command: ❯ sase listen",)
    assert _update_command_details(("listen",), declared) == ()
    assert _update_command_details(("old",), declared) == (
        "❯ Adds command: ❯ sase listen",
        "❯ Removes command: ❯ sase old",
    )
    assert _update_command_details((), None) == ()
    assert _update_command_details((), DeclaredCommands(status="unknown")) == ()


def test_confirm_modal_renders_warnings_yellow() -> None:
    from sase.ace.tui.modals.plugin_action_confirm_modal import (
        PluginActionConfirmModal,
    )

    modal = PluginActionConfirmModal(
        title="Install listen",
        intro="Confirm to install listen.",
        variants=[
            PluginActionVariant(
                key="index",
                label="from index",
                argv=("uv", "tool", "install"),
                summary="Installs listen",
                details=("❯ Adds a new command: ❯ sase listen",),
                warnings=("sase listen would conflict with sase-listen",),
            )
        ],
        panel_title="Confirm install",
    )
    text = _render(modal._preview_renderable())
    assert "❯ Adds a new command: ❯ sase listen" in text
    assert "sase listen would conflict with sase-listen" in text


# --------------------------------------------------------------------------- #
# v4 receipt codec
# --------------------------------------------------------------------------- #


def test_receipt_v4_round_trips_command_changes() -> None:
    receipt = UpdateToastReceipt(
        kind="managed",
        created_at=123.0,
        primary=None,
        plugins=(
            UpdateVersionTransition(
                "listen",
                None,
                "0.1.2",
                commands_added=("listen",),
                commands_removed=("old",),
            ),
        ),
    )
    payload = receipt_to_json(receipt)
    assert payload["format"] == 4
    assert payload["plugins"][0]["commands_added"] == ["listen"]
    assert payload["plugins"][0]["commands_removed"] == ["old"]
    assert receipt_from_json(payload) == receipt


def test_receipt_v3_without_command_keys_still_decodes() -> None:
    receipt = UpdateToastReceipt(
        kind="managed",
        created_at=123.0,
        primary=None,
        plugins=(UpdateVersionTransition("listen", None, "0.1.2"),),
    )
    payload = receipt_to_json(receipt)
    payload["format"] = 3
    del payload["plugins"][0]["commands_added"]
    del payload["plugins"][0]["commands_removed"]
    decoded = receipt_from_json(payload)
    assert decoded is not None
    assert decoded.plugins[0].commands_added == ()
    assert decoded.plugins[0].commands_removed == ()


def test_receipt_rejects_malformed_command_lists() -> None:
    receipt = UpdateToastReceipt(
        kind="managed",
        created_at=123.0,
        primary=None,
        plugins=(UpdateVersionTransition("listen", None, "0.1.2"),),
    )
    payload = receipt_to_json(receipt)
    payload["plugins"][0]["commands_added"] = ["listen", ""]
    assert receipt_from_json(payload) is None


# --------------------------------------------------------------------------- #
# Lifecycle-effects receipt builders
# --------------------------------------------------------------------------- #


def _install_outcome(
    effects: PluginChangeEffects,
) -> InstallOutcome:
    return InstallOutcome(
        plan=InstallReady(
            spec=ResolvedSpec(
                requirement=Requirement.from_spec("sase-listen"),
                display_name="listen",
                source="catalog",
            ),
            argv=["uv", "tool", "install"],
        ),
        change_set=UvChangeSet(
            changes=(
                UvPackageChange(
                    name="sase-listen",
                    kind=ChangeKind.ADDED,
                    new_version="0.1.2",
                ),
            )
        ),
        groups=(),
        elapsed=0.0,
        effects=effects,
    )


def _effects(changes: CommandChanges) -> PluginChangeEffects:
    return PluginChangeEffects(
        command_changes=changes,
        completion_refresh=CompletionRefreshReport(attempted=False, outcomes=()),
    )


def test_install_receipt_attributes_commands_from_effects() -> None:
    effects = _effects(
        CommandChanges(
            added=(
                _CommandChange(
                    name="listen", distribution="sase-listen", version="0.1.2"
                ),
            )
        )
    )
    receipt = build_update_receipt(_install_outcome(effects), created_at=123.0)
    assert receipt is not None
    assert receipt.plugins[0].commands_added == ("listen",)
    assert receipt.plugins[0].commands_removed == ()


def test_install_receipt_ignores_other_distributions_commands() -> None:
    effects = _effects(
        CommandChanges(
            added=(
                _CommandChange(
                    name="other", distribution="sase-other", version="1.0.0"
                ),
            )
        )
    )
    receipt = build_update_receipt(_install_outcome(effects), created_at=123.0)
    assert receipt is not None
    assert receipt.plugins[0].commands_added == ()


# --------------------------------------------------------------------------- #
# Toast command lines
# --------------------------------------------------------------------------- #


def test_toast_renders_added_and_removed_commands() -> None:
    receipt = UpdateToastReceipt(
        kind="managed",
        created_at=123.0,
        primary=None,
        plugins=(
            UpdateVersionTransition(
                "listen",
                None,
                "0.1.2",
                commands_added=("listen",),
            ),
            UpdateVersionTransition(
                "gone",
                "1.0.0",
                None,
                commands_removed=("gone-cmd",),
            ),
        ),
    )
    message = post_update_toast._format_post_update_toast_message(receipt)
    assert "❯ sase listen" in message and "new command" in message
    assert "❯ sase gone-cmd" in message and "removed" in message


def test_toast_omits_command_lines_without_changes() -> None:
    receipt = update_receipt.UpdateToastReceipt(
        kind="managed",
        created_at=123.0,
        primary=None,
        plugins=(UpdateVersionTransition("listen", None, "0.1.2"),),
    )
    message = post_update_toast._format_post_update_toast_message(receipt)
    assert "❯ sase" not in message
