"""Exact AXE config-action adapter and non-blocking action coverage."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import patch

from sase.ace.tui.actions.axe_config_actions import AxeConfigActionsMixin
from sase.ace.tui.actions.axe_config_actions._backend import (
    AxeAppliedConfigOutcome,
    AxeConfigActionInventory,
    _build_axe_editor_seed,
    _plan_axe_editor_request,
    axe_base_chop_identities,
)
from sase.ace.tui.modals import (
    AxeEntryIdentity,
    AxeEntryEditorResult,
    AxeEntryMutationRequest,
    SchemaFieldOperation,
)
from sase.ace.tui.widgets.bgcmd_list import ChopItem, LumberjackItem
from sase.axe.chop_inventory import ChopInventory
from sase.axe.config_backend import (
    AxeConfigComposition,
    AxeEntrySelector,
    AxeFieldProvenance,
    AxeInventoryEntry,
    AxeRawContribution,
    compose_axe_config,
)
from sase.config.core import ConfigLayer
from sase.config import AppliedResult
from sase.config.inventory import load_config_schema


def _empty_chop_inventory() -> ChopInventory:
    return ChopInventory((), (), (), "/venv/bin", ())


def _composition(path: Path) -> AxeConfigComposition:
    selector = AxeEntrySelector.chop_entry("checks.main", "lint.rule")
    entry = AxeInventoryEntry(
        selector=selector,
        key_path=(
            "axe",
            "lumberjacks",
            "checks.main",
            "chops",
            "lint.rule",
        ),
        path="axe.lumberjacks.checks.main.chops.lint.rule",
        effective={
            "script": "sase_chop_lint",
            "description": "effective",
            "enabled": False,
        },
        enabled=False,
        mutable=True,
        generated=False,
        base_selector=None,
        target_key=None,
        field_provenance=(
            AxeFieldProvenance(
                (
                    "axe",
                    "lumberjacks",
                    "checks.main",
                    "chops",
                    "lint.rule",
                    "script",
                ),
                "axe.lumberjacks.checks.main.chops.lint.rule.script",
                "user",
            ),
            AxeFieldProvenance(
                (
                    "axe",
                    "lumberjacks",
                    "checks.main",
                    "chops",
                    "lint.rule",
                    "description",
                ),
                "axe.lumberjacks.checks.main.chops.lint.rule.description",
                "overlay:test",
            ),
        ),
        contributions=(
            AxeRawContribution(
                "user",
                str(path),
                True,
                "map",
                True,
                {"script": "sase_chop_lint", "enabled": False},
            ),
            AxeRawContribution(
                "overlay:test",
                str(path.with_name("sase_test.yml")),
                True,
                "map",
                True,
                {"description": "effective"},
            ),
        ),
    )
    return AxeConfigComposition(
        schema_version=1,
        effective_config={},
        provenance=entry.field_provenance,
        entries=(entry,),
        diagnostics=(),
        layer_inputs=(
            {
                "name": "default",
                "kind": "builtin",
                "path": None,
                "writable": False,
                "exists": True,
                "list_strategy": "concatenate",
            },
            {
                "name": "user",
                "kind": "user",
                "path": str(path),
                "writable": True,
                "exists": True,
                "list_strategy": "replace",
            },
            {
                "name": "overlay:test",
                "kind": "overlay",
                "path": str(path.with_name("sase_test.yml")),
                "writable": True,
                "exists": True,
                "list_strategy": "concatenate",
            },
        ),
    )


def test_edit_seed_maps_exact_scopes_contributions_and_provenance(
    tmp_path: Path,
) -> None:
    composition = _composition(tmp_path / "sase.yml")
    inventory = AxeConfigActionInventory(
        composition,
        load_config_schema(),
        _empty_chop_inventory(),
        True,
    )
    selector = AxeEntrySelector.chop_entry("checks.main", "lint.rule")
    seed = _build_axe_editor_seed(
        inventory,
        selector,
        generated_instance="lint.rule[project=sase]",
        generated_warning="Editing the base affects every generated instance.",
    )
    assert seed.initial_target == "overlay:test"
    assert seed.raw_values_by_scope == {
        "user": {"script": "sase_chop_lint", "enabled": False},
        "overlay:test": {"description": "effective"},
    }
    assert seed.provenance == {
        "script": ("user",),
        "description": ("overlay:test",),
    }
    assert seed.status == "disabled"
    assert seed.identity.generated_instance == "lint.rule[project=sase]"
    assert axe_base_chop_identities(composition) == {("checks.main", "lint.rule")}


def test_new_entry_seed_marks_only_intentional_initial_values(tmp_path: Path) -> None:
    inventory = AxeConfigActionInventory(
        _composition(tmp_path / "sase.yml"),
        load_config_schema(),
        _empty_chop_inventory(),
        False,
    )
    seed = _build_axe_editor_seed(
        inventory,
        AxeEntrySelector.chop_entry("checks.main", "new chop"),
        new_entry=True,
        initial_values={"script": "sase_chop_new"},
        initial_touched=("script",),
    )
    from sase.ace.tui.modals import AxeEntryEditorModal

    modal = AxeEntryEditorModal(seed)
    assert modal._form.operations() == (
        SchemaFieldOperation.set_value(("script",), "sase_chop_new"),
    )


def test_sparse_plan_projects_missing_script_warning_and_exact_diff(
    tmp_path: Path,
) -> None:
    target = tmp_path / "sase.yml"
    data = {
        "axe": {
            "lumberjacks": {
                "checks.main": {
                    "interval": 5,
                    "chops": {"lint.rule": {"script": "definitely_missing_chop"}},
                }
            }
        }
    }
    target.write_text(
        "axe:\n"
        "  lumberjacks:\n"
        "    checks.main:\n"
        "      interval: 5\n"
        "      chops:\n"
        "        lint.rule:\n"
        "          script: definitely_missing_chop\n",
        encoding="utf-8",
    )
    composition = compose_axe_config(
        [
            ConfigLayer(
                name="user",
                path=str(target),
                exists=True,
                list_strategy="replace",
                data=data,
            )
        ]
    )
    inventory = AxeConfigActionInventory(
        composition,
        load_config_schema(),
        _empty_chop_inventory(),
        False,
    )
    request = AxeEntryMutationRequest(
        identity=AxeEntryIdentity("chop", "checks.main", "lint.rule"),
        target_scope="user",
        operations=(
            SchemaFieldOperation.set_value(("description",), "new description"),
        ),
    )
    with patch(
        "sase.ace.tui.actions.axe_config_actions._backend.discover_chop_script",
        return_value=None,
    ):
        plan = _plan_axe_editor_request(
            inventory,
            AxeEntrySelector.chop_entry("checks.main", "lint.rule"),
            request,
        )
    assert "description: new description" in plan.preview.text_diff
    assert any("was not found" in warning for warning in plan.preview.warnings)
    assert plan.preview.effective is not None
    assert plan.preview.effective.after["description"] == "new description"


class _ActionHarness(AxeConfigActionsMixin):
    def __init__(self) -> None:
        self.current_tab = "axe"
        self.current_idx = 0
        self._axe_items: list[Any] = [LumberjackItem(name="hooks")]
        self.pushed: list[tuple[object, object]] = []
        self.notifications: list[str] = []

    def push_screen(self, screen: object, callback: object = None) -> None:
        self.pushed.append((screen, callback))

    def notify(self, message: str, **_kwargs: Any) -> None:
        self.notifications.append(message)


def test_action_opening_uses_cached_identity_without_sync_inventory_reads() -> None:
    app = _ActionHarness()
    with patch(
        "sase.ace.tui.actions.axe_config_actions._mixin."
        "load_axe_config_action_inventory"
    ) as loader:
        app.action_add_axe_item()
    loader.assert_not_called()
    assert app.pushed

    calls: list[tuple[str, object, object]] = []
    app._start_axe_config_inventory_load = (  # type: ignore[method-assign]
        lambda purpose, *, guard, parent: calls.append((purpose, guard, parent))
    )
    app._open_selected_axe_entry_editor()
    assert calls == [("edit", ("lumberjack", "hooks"), None)]


def test_contextual_add_uses_selected_chop_parent() -> None:
    app = _ActionHarness()
    app._axe_items = [ChopItem(lumberjack_name="hooks", chop_name="lint")]
    app.action_add_axe_item()
    chooser, callback = app.pushed[-1]
    assert chooser.contextual_lumberjack == "hooks"  # type: ignore[attr-defined]
    calls: list[tuple[str, object, object]] = []
    app._start_axe_config_inventory_load = (  # type: ignore[method-assign]
        lambda purpose, *, guard, parent: calls.append((purpose, guard, parent))
    )
    callback("chop")  # type: ignore[operator]
    assert calls == [("new_chop", ("chop", "hooks", "lint"), "hooks")]


class _WriteHarness(AxeConfigActionsMixin):
    def __init__(self) -> None:
        self._axe_worker = None
        self._axe_config_restart_saved_path = None
        self._axe_pending_selection = None
        self.notifications: list[tuple[str, str]] = []
        self.refreshes = 0
        self.restarts: list[str] = []
        self.commit_paths: list[str] = []

    def _selected_axe_config_key(self):  # type: ignore[no-untyped-def, override]
        return ("lumberjack", "hooks")

    def _schedule_axe_async_refresh(self) -> None:
        self.refreshes += 1

    def _restart_axe_daemon(self, *, source: str) -> None:
        self.restarts.append(source)

    def _schedule_axe_config_commit_offer(self, path: str) -> None:
        self.commit_paths.append(path)

    def notify(self, message: str, *, severity: str = "information", **_: Any) -> None:
        self.notifications.append((message, severity))


def _editor_result(*, running: bool, restart: bool) -> AxeEntryEditorResult:
    applied = AppliedResult(
        path="/tmp/sase.yml",
        op="set",
        key_path=("axe",),
        created=False,
        used_chezmoi=False,
    )
    return AxeEntryEditorResult(
        identity=AxeEntryIdentity("lumberjack", "hooks"),
        applied=AxeAppliedConfigOutcome(applied, running),
        restart_requested=restart,
    )


def test_successful_write_restarts_only_when_verified_running() -> None:
    app = _WriteHarness()
    session = SimpleNamespace(display_target=("lumberjack", "hooks"))
    app._finish_axe_config_write(
        cast(Any, session), _editor_result(running=True, restart=True)
    )
    assert app.restarts == ["ace AXE config edit"]
    assert app._axe_config_restart_saved_path == "/tmp/sase.yml"
    assert app.refreshes == 1
    assert app.commit_paths == ["/tmp/sase.yml"]

    stopped = _WriteHarness()
    stopped._finish_axe_config_write(
        cast(Any, session), _editor_result(running=False, restart=True)
    )
    assert stopped.restarts == []
    assert "stopped before restart" in stopped.notifications[0][0]


def test_save_only_running_reports_old_runtime_config() -> None:
    app = _WriteHarness()
    session = SimpleNamespace(display_target=("lumberjack", "hooks"))
    app._finish_axe_config_write(
        cast(Any, session), _editor_result(running=True, restart=False)
    )
    assert "keeps its previous config until restarted" in app.notifications[0][0]
