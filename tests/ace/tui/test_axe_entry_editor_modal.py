"""Reusable AXE entry editor behavior and layout coverage."""

from __future__ import annotations

from dataclasses import replace
from typing import Any

from sase.ace.testing import AcePage
from sase.ace.tui.modals.axe_entry_editor_modal import (
    AxeEntryEditorModal,
    AxeEntryEditorSeed,
    AxeEntryIdentity,
    AxeEntryMutationRequest,
    AxeWritableScope,
)
from sase.ace.tui.modals.config_transaction_preview import (
    ConfigTransactionPreview,
    TransactionEffectivePreview,
)
from sase.config.inventory import load_config_schema


_CHOP_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "script": {"type": "string", "minLength": 1, "description": "Executable."},
        "description": {"type": "string", "description": "What it does."},
        "enabled": {"type": "boolean", "default": True},
        "run_every": {"type": "string", "pattern": r"^\d+[smh]$"},
        "timeout": {"type": "string", "pattern": r"^\d+[smh]$"},
        "env": {"type": "object", "additionalProperties": True},
        "inhibit_if": {"oneOf": [{"type": "array"}, {"type": "object"}]},
        "trigger": {"oneOf": [{"type": "string"}, {"type": "object"}]},
        "once_per": {"oneOf": [{"type": "string"}, {"type": "object"}]},
        "for_each": {"type": "array", "items": {"type": "object"}},
        "vars": {"type": "object", "additionalProperties": True},
    },
}


def _seed(*, running: bool = False) -> AxeEntryEditorSeed:
    return AxeEntryEditorSeed(
        identity=AxeEntryIdentity(
            "chop",
            "checks",
            "lint",
            generated_instance="lint[project=sase]",
        ),
        schema=_CHOP_SCHEMA,
        writable_scopes=(
            AxeWritableScope("user", "/tmp/sase.yml", "user"),
            AxeWritableScope("overlay:test", "/tmp/sase_test.yml", "overlay"),
        ),
        effective_values={"script": "sase_lint", "enabled": True},
        raw_values={"script": "sase_lint"},
        inherited_values={"enabled": True},
        provenance={"script": "user", "enabled": "default"},
        generated_warning="Editing the base chop affects every generated instance.",
        running=running,
    )


def _preview() -> ConfigTransactionPreview:
    return ConfigTransactionPreview(
        target_path="/tmp/sase.yml",
        effective=TransactionEffectivePreview(True, "old", True, "new", True),
        diagnostics=(),
        warnings=("missing executable is checked by the caller",),
        text_diff="@@ -1 +1 @@\n-old\n+new\n",
    )


def test_bundled_lumberjack_and_chop_friendly_field_order() -> None:
    schema = load_config_schema()
    scope = (AxeWritableScope("user"),)
    lumberjack = AxeEntryEditorModal(
        AxeEntryEditorSeed(
            identity=AxeEntryIdentity("lumberjack", "checks"),
            schema=schema,
            writable_scopes=scope,
            effective_values={"interval": 1},
        )
    )
    assert [field.name for field in lumberjack._form.fields] == [
        "interval",
        "chop_timeout",
        "env",
    ]
    assert lumberjack._form.field("env").editor_kind == "yaml"

    chop = AxeEntryEditorModal(
        AxeEntryEditorSeed(
            identity=AxeEntryIdentity("chop", "checks", "lint"),
            schema=schema,
            writable_scopes=scope,
            effective_values={"script": "sase_lint"},
        )
    )
    assert [field.name for field in chop._form.fields] == [
        "script",
        "description",
        "enabled",
        "run_every",
        "timeout",
        "env",
        "inhibit_if",
        "trigger",
        "once_per",
        "for_each",
        "vars",
    ]
    assert all(
        chop._form.field(name).editor_kind == "yaml"
        for name in (
            "env",
            "inhibit_if",
            "trigger",
            "once_per",
            "for_each",
            "vars",
        )
    )


def test_new_seed_intentionally_touches_only_declared_initial_fields() -> None:
    modal = AxeEntryEditorModal(
        AxeEntryEditorSeed(
            identity=AxeEntryIdentity("chop", "checks", "new"),
            schema=_CHOP_SCHEMA,
            writable_scopes=(AxeWritableScope("user"),),
            effective_values={"script": "sase_chop_new", "enabled": True},
            new_entry=True,
            initial_touched=("script",),
        )
    )
    assert [operation.key_path for operation in modal._form.operations()] == [
        ("script",)
    ]
    assert modal._title_text().plain.startswith("Add AXE chop")


def test_scope_change_refreshes_target_contribution_without_touching_draft() -> None:
    seed = _seed()
    seed = replace(
        seed,
        raw_values_by_scope={
            "user": {"script": "sase_lint"},
            "overlay:test": {},
        },
    )
    modal = AxeEntryEditorModal(seed)
    modal._form = modal._form.set_value("script", "draft")
    modal.action_cycle_scope()
    assert modal._target == "overlay:test"
    assert not modal._form.field("script").has_target
    assert modal._form.field("script").draft_value == "draft"


async def test_chop_groups_picker_badges_warning_and_narrow_layout() -> None:
    async with AcePage(size=(70, 36)) as page:
        modal = AxeEntryEditorModal(_seed(), plan=lambda _request: _preview())
        page.app.push_screen(modal)
        await page.expect_modal("AxeEntryEditorModal")
        await page.wait_for(lambda _screen: modal.has_class("-narrow"))
        assert modal.has_class("-narrow")
        assert modal.query_one("#axe-editor-basics-header").render().plain == "Basics"
        assert modal.query_one("#axe-editor-advanced-header").render().plain == (
            "Advanced"
        )
        assert "[user]" in modal._field_row(modal._form.field("script")).plain
        assert "every generated instance" in modal._status_text().plain
        description_index = next(
            index
            for index, field in enumerate(modal._form.fields)
            if field.name == "description"
        )
        await page.click(f"#axe-editor-field-{description_index}")
        assert modal._active_name == "description"
        modal.action_add_property()
        await page.expect_modal("PropertyPickerModal")
        picker = page.app.screen
        assert isinstance(picker, object)
        picker._select_index(0)  # type: ignore[attr-defined]
        await page.expect_modal("AxeEntryEditorModal")
        await page.wait_for(lambda _screen: len(modal._form.visible_fields()) == 4)
        assert len(modal._form.visible_fields()) == 4


async def test_preview_back_retains_sparse_draft_and_running_primary_restarts() -> None:
    requests: list[AxeEntryMutationRequest] = []
    applied: list[object] = []
    result: list[object] = []

    def plan(request: AxeEntryMutationRequest) -> ConfigTransactionPreview:
        requests.append(request)
        return _preview()

    def apply(plan_value: object) -> str:
        applied.append(plan_value)
        return "written"

    async with AcePage() as page:
        modal = AxeEntryEditorModal(_seed(running=True), plan=plan, apply=apply)
        page.app.push_screen(modal, result.append)
        await page.expect_modal("AxeEntryEditorModal")
        modal._form = modal._form.set_value("script", "sase_check")
        modal._render_all(force_editor=True)
        modal.action_confirm()
        await page.wait_for(lambda _screen: modal._plan is not None)
        assert requests[0].operations[0].key_path == ("script",)
        modal.action_back()
        assert modal._form.field("script").draft_value == "sase_check"
        modal.action_confirm()
        await page.wait_for(lambda _screen: modal._plan is not None)
        modal.action_confirm()
        await page.wait_for(lambda _screen: bool(result))
    assert applied
    assert result[0].restart_requested is True  # type: ignore[attr-defined]


async def test_stopped_save_and_running_save_only_never_request_restart() -> None:
    for seed, save_only in ((_seed(), False), (_seed(running=True), True)):
        result: list[object] = []
        async with AcePage() as page:
            modal = AxeEntryEditorModal(
                seed,
                plan=lambda _request: _preview(),
                apply=lambda _plan: "written",
            )
            page.app.push_screen(modal, result.append)
            await page.expect_modal("AxeEntryEditorModal")
            modal._form = modal._form.set_value("script", "changed")
            modal.action_confirm()
            await page.wait_for(
                lambda _screen, current_modal=modal: current_modal._plan is not None
            )
            if save_only:
                modal.action_save_only()
            else:
                modal.action_confirm()
            await page.wait_for(
                lambda _screen, current_result=result: bool(current_result)
            )
        assert result[0].restart_requested is False  # type: ignore[attr-defined]
