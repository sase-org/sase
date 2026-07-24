"""Tests for the Models panel's persistent Edit/Reset wiring and preview modal.

Phase 3 (epic sase-5e): covers the ``e`` (Edit) / ``r`` (Reset) actions on
:class:`ModelsPanel` — the model-picker / custom-input entry points, the
post-write row refresh and commit/push offer — plus the
:class:`AliasEditPreviewModal` plan → preview → write worker flow.
"""

from __future__ import annotations

import subprocess
from typing import Any
from unittest.mock import MagicMock

from textual.app import App, ComposeResult
from textual.widgets import Static

import sase.ace.tui.modals.models_panel as models_panel
import sase.ace.tui.modals.models_panel_edit as models_panel_edit
from sase.ace.tui.modals.confirm_action_modal import ConfirmActionModal
from sase.ace.tui.modals.custom_model_input_modal import CustomModelInputModal
from sase.ace.tui.modals.model_picker_modal import (
    CUSTOM_SENTINEL,
    AliasSelectionContext,
    ModelPickerModal,
)
from sase.ace.tui.modals.models_panel import ModelsPanel
from sase.ace.tui.modals.models_panel_edit import AliasEditPreviewModal
from sase.ace.tui.modals.models_panel_edit_helpers import (
    AliasCommitOffer,
    AliasEditOutcome,
)
from sase.ace.tui.modals.models_panel_effort_cards import (
    DefaultEffortLevelChoice,
    DefaultEffortLevelModal,
)
from sase.config import AppliedResult, ConfigEditOp
from sase.config.edit import ConfigEffectivePreview, ConfigWritePlan, EditPlanResult
from sase.config.inventory import ConfigDiagnostic
from sase.llm_provider import AliasKind, AliasView, TemporaryLLMOverride


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------


class _TestApp(App[None]):
    ENABLE_COMMAND_PALETTE = False

    def compose(self) -> ComposeResult:
        yield from ()


def _view(
    name: str,
    kind: AliasKind,
    *,
    configured: bool = False,
    configured_value: str | None = None,
    provider: str | None = "claude",
    model: str = "opus",
    override: TemporaryLLMOverride | None = None,
    configured_source: str | None = None,
    description: str | None = None,
) -> AliasView:
    return AliasView(
        name=name,
        kind=kind,
        configured=configured,
        configured_value=configured_value,
        provider=provider,
        model=model,
        override=override,
        configured_source=configured_source,
        description=description,
    )


def _patch_views(monkeypatch: Any, views: list[AliasView]) -> None:
    monkeypatch.setattr(models_panel, "build_alias_views", lambda *a, **k: views)
    monkeypatch.setattr(models_panel, "_now", lambda: 0.0)


def _make_plan(
    *,
    op: str = "set",
    value: str | None = "opus",
    target_path: str = "/tmp/sase.yml",
    diff: str = "@@ -1 +1 @@\n-coder: old\n+coder: opus\n",
    valid: bool = True,
    used_chezmoi: bool = False,
) -> EditPlanResult:
    write_plan = ConfigWritePlan(
        file=target_path,
        layer="user",
        key_path=("llm_provider", "model_aliases", "builtin", "coder"),
        op=op,
        has_value=op == "set",
        new_value=value if op == "set" else None,
    )
    preview = ConfigEffectivePreview(
        path="llm_provider.model_aliases.builtin.coder",
        has_before=True,
        before="old",
        has_after=op == "set",
        after=value if op == "set" else None,
        changed=True,
    )
    validation: tuple[ConfigDiagnostic, ...] = ()
    if not valid:
        validation = (
            ConfigDiagnostic(
                severity="error",
                code="bad",
                message="bad value",
                path="llm_provider.model_aliases.builtin.coder",
                layer="user",
            ),
        )
    return EditPlanResult(
        schema_version=1,
        write_plan=write_plan,
        candidate_config={},
        effective_preview=preview,
        validation=validation,
        diagnostics=(),
        target_path=target_path,
        used_chezmoi=used_chezmoi,
        current_text="coder: old\n",
        new_text="coder: opus\n" if op == "set" else "",
        text_diff=diff,
    )


async def _wait_for(pilot: Any, pred: Any, *, tries: int = 400) -> None:
    for _ in range(tries):
        if pred():
            return
        await pilot.pause()
    raise AssertionError("condition was not satisfied in time")


# ---------------------------------------------------------------------------
# Panel — Edit entry points
# ---------------------------------------------------------------------------


async def test_action_edit_opens_model_picker(monkeypatch: Any) -> None:
    _patch_views(monkeypatch, [_view("coder", "role")])
    monkeypatch.setattr(
        models_panel_edit, "plan_alias_edit", lambda *a, **k: _make_plan()
    )
    async with _TestApp().run_test() as pilot:
        pilot.app.push_screen(ModelsPanel())
        await pilot.pause()
        await pilot.press("l", "e")
        await pilot.pause()
        assert isinstance(pilot.app.screen, ModelPickerModal)


async def test_action_edit_picker_uses_flat_alias_snapshot(monkeypatch: Any) -> None:
    views = [
        _view("coder", "role"),
        _view(
            "bucketed_a",
            "user",
            configured=True,
            configured_value="claude/opus",
            configured_source="custom",
        ),
        _view(
            "bucketed_b",
            "user",
            configured=True,
            configured_value="codex/o3",
            provider="codex",
            model="o3",
            configured_source="custom",
        ),
    ]
    _patch_views(monkeypatch, views)

    async with _TestApp().run_test() as pilot:
        panel = ModelsPanel()
        pilot.app.push_screen(panel)
        await pilot.pause()
        await pilot.press("l", "e")
        await pilot.pause()

        picker = pilot.app.screen
        assert isinstance(picker, ModelPickerModal)
        assert picker._alias_context is not None
        assert picker._alias_context.views == tuple(views)
        ids = {row.option_id for row in picker._all_rows}
        assert {"@bucketed_a", "@bucketed_b"} <= ids


async def test_on_edit_model_picked_opens_preview_with_set_op(monkeypatch: Any) -> None:
    view = _view("coder", "role")
    _patch_views(monkeypatch, [view])
    monkeypatch.setattr(
        models_panel_edit, "plan_alias_edit", lambda *a, **k: _make_plan()
    )

    async with _TestApp().run_test() as pilot:
        panel = ModelsPanel()
        pilot.app.push_screen(panel)
        await pilot.pause()
        panel._pending_edit_view = view
        panel._on_edit_model_picked("opus")
        await pilot.pause()
        assert isinstance(pilot.app.screen, DefaultEffortLevelModal)
        panel._on_edit_model_effort_picked(DefaultEffortLevelChoice("medium"))
        await pilot.pause()
        screen = pilot.app.screen
        assert isinstance(screen, AliasEditPreviewModal)
        assert screen._op.kind == "set"
        assert screen._op.value == "opus@medium"


async def test_on_edit_alias_picked_persists_raw_reference(monkeypatch: Any) -> None:
    target = _view("big_epic_lander", "role")
    coder = _view("coder", "role", provider="codex", model="o3")
    _patch_views(monkeypatch, [target, coder])
    monkeypatch.setattr(
        models_panel_edit, "plan_alias_edit", lambda *a, **k: _make_plan()
    )

    async with _TestApp().run_test() as pilot:
        panel = ModelsPanel()
        pilot.app.push_screen(panel)
        await pilot.pause()
        panel._pending_edit_view = target
        panel._pending_alias_selection = AliasSelectionContext(
            (target, coder), target.name, "persistent"
        )
        panel._on_edit_model_picked("@coder")
        await pilot.pause()

        assert isinstance(pilot.app.screen, DefaultEffortLevelModal)
        panel._on_edit_model_effort_picked(DefaultEffortLevelChoice("xhigh"))
        await pilot.pause()
        screen = pilot.app.screen
        assert isinstance(screen, AliasEditPreviewModal)
        assert screen._op.value == "@coder@xhigh"


async def test_on_edit_model_picked_custom_then_preview(monkeypatch: Any) -> None:
    view = _view("coder", "role")
    _patch_views(monkeypatch, [view])
    monkeypatch.setattr(
        models_panel_edit, "plan_alias_edit", lambda *a, **k: _make_plan()
    )

    async with _TestApp().run_test() as pilot:
        panel = ModelsPanel()
        pilot.app.push_screen(panel)
        await pilot.pause()
        panel._pending_edit_view = view
        panel._on_edit_model_picked(CUSTOM_SENTINEL)
        await pilot.pause()
        assert isinstance(pilot.app.screen, CustomModelInputModal)
        panel._on_edit_custom_picked("@default")
        await pilot.pause()
        assert isinstance(pilot.app.screen, DefaultEffortLevelModal)
        panel._on_edit_model_effort_picked(DefaultEffortLevelChoice("medium"))
        await pilot.pause()
        screen = pilot.app.screen
        assert isinstance(screen, AliasEditPreviewModal)
        assert screen._op.value == "@default@medium"


async def test_on_edit_custom_rejects_unknown_and_cyclic_aliases(
    monkeypatch: Any,
) -> None:
    target = _view("coder", "role")
    dependent = _view(
        "dependent",
        "user",
        configured=True,
        configured_value="@coder",
    )
    _patch_views(monkeypatch, [target, dependent])

    async with _TestApp().run_test() as pilot:
        panel = ModelsPanel()
        pilot.app.push_screen(panel)
        await pilot.pause()
        panel.notify = MagicMock()  # type: ignore[method-assign]
        panel._pending_edit_view = target
        panel._pending_alias_selection = AliasSelectionContext(
            (target, dependent), target.name, "persistent"
        )

        panel._on_edit_custom_picked("@missing")
        panel._on_edit_custom_picked("@dependent@medium")
        await pilot.pause()

        assert isinstance(pilot.app.screen, ModelsPanel)
        assert panel.notify.call_count == 2
        messages = [call.args[0] for call in panel.notify.call_args_list]
        assert "unknown alias" in messages[0]
        assert "would create a cycle" in messages[1]


async def test_on_edit_custom_accepts_fallback_and_rejects_mixed_selector(
    monkeypatch: Any,
) -> None:
    view = _view("smartest", "role")
    _patch_views(monkeypatch, [view])
    monkeypatch.setattr(
        models_panel_edit, "plan_alias_edit", lambda *a, **k: _make_plan()
    )

    async with _TestApp().run_test() as pilot:
        panel = ModelsPanel()
        pilot.app.push_screen(panel)
        await pilot.pause()
        panel.notify = MagicMock()  # type: ignore[method-assign]
        panel._pending_edit_view = view

        panel._on_edit_custom_picked(
            "claude/claude-fable-5@low || codex/gpt-5.6-sol@high"
        )
        await pilot.pause()
        assert isinstance(pilot.app.screen, AliasEditPreviewModal)
        assert pilot.app.screen._op.value == (
            "claude/claude-fable-5@low || codex/gpt-5.6-sol@high"
        )

        pilot.app.pop_screen()
        await pilot.pause()
        panel._on_edit_custom_picked("claude/opus | codex/o3 || claude/sonnet")
        await pilot.pause()
        assert isinstance(pilot.app.screen, ModelsPanel)
        assert "cannot mix" in panel.notify.call_args.args[0]


async def test_on_edit_custom_preserves_alias_selector_member_efforts(
    monkeypatch: Any,
) -> None:
    view = _view(
        "blogger",
        "user",
        configured=True,
        configured_source="custom",
    )
    _patch_views(monkeypatch, [view])
    monkeypatch.setattr(
        models_panel_edit, "plan_alias_edit", lambda *a, **k: _make_plan()
    )
    monkeypatch.setattr(
        "sase.ace.tui.modals.models_panel_alias_edit."
        "validate_model_alias_selector_value",
        lambda *a, **k: (),
    )

    async with _TestApp().run_test() as pilot:
        panel = ModelsPanel()
        pilot.app.push_screen(panel)
        await pilot.pause()
        panel._pending_edit_view = view
        value = "@default@low | @coder@high"
        panel._on_edit_custom_picked(value)
        await pilot.pause()

        screen = pilot.app.screen
        assert isinstance(screen, AliasEditPreviewModal)
        assert screen._op.value == value
        assert panel._pending_edit_raw_model == value


async def test_on_edit_model_picked_cancel_is_noop(monkeypatch: Any) -> None:
    _patch_views(monkeypatch, [_view("coder", "role")])

    async with _TestApp().run_test() as pilot:
        panel = ModelsPanel()
        pilot.app.push_screen(panel)
        await pilot.pause()
        panel._on_edit_model_picked(None)
        await pilot.pause()
        assert isinstance(pilot.app.screen, ModelsPanel)


async def test_on_edit_custom_explicit_alias_effort_skips_effort_picker(
    monkeypatch: Any,
) -> None:
    view = _view("coder", "role")
    _patch_views(monkeypatch, [view])
    monkeypatch.setattr(
        models_panel_edit, "plan_alias_edit", lambda *a, **k: _make_plan()
    )

    async with _TestApp().run_test() as pilot:
        panel = ModelsPanel()
        pilot.app.push_screen(panel)
        await pilot.pause()
        panel._pending_edit_view = view
        panel._on_edit_custom_picked("@default@medium")
        await pilot.pause()

        screen = pilot.app.screen
        assert isinstance(screen, AliasEditPreviewModal)
        assert screen._op.value == "@default@medium"


async def test_on_edit_effort_cancel_does_not_open_preview(
    monkeypatch: Any,
) -> None:
    view = _view("coder", "role")
    _patch_views(monkeypatch, [view])

    async with _TestApp().run_test() as pilot:
        panel = ModelsPanel()
        pilot.app.push_screen(panel)
        await pilot.pause()
        panel._pending_edit_view = view
        panel._on_edit_model_picked("opus")
        await pilot.pause()
        assert isinstance(pilot.app.screen, DefaultEffortLevelModal)
        panel._on_edit_model_effort_picked(None)
        await pilot.pause()

        assert isinstance(pilot.app.screen, DefaultEffortLevelModal)


# ---------------------------------------------------------------------------
# Panel — Reset
# ---------------------------------------------------------------------------


async def test_action_reset_unconfigured_warns_and_skips(monkeypatch: Any) -> None:
    _patch_views(monkeypatch, [_view("coder", "role", configured=False)])

    async with _TestApp().run_test() as pilot:
        panel = ModelsPanel()
        pilot.app.push_screen(panel)
        await pilot.pause()
        await pilot.press("l")
        panel.notify = MagicMock()  # type: ignore[method-assign]
        panel.action_reset()
        await pilot.pause()
        assert isinstance(pilot.app.screen, ModelsPanel)
        panel.notify.assert_called_once()
        assert panel.notify.call_args.kwargs.get("severity") == "warning"


async def test_action_reset_configured_opens_preview_with_unset(
    monkeypatch: Any,
) -> None:
    _patch_views(
        monkeypatch,
        [_view("coder", "role", configured=True, configured_value="opus")],
    )
    monkeypatch.setattr(
        models_panel_edit, "plan_alias_edit", lambda *a, **k: _make_plan(op="unset")
    )

    async with _TestApp().run_test() as pilot:
        panel = ModelsPanel()
        pilot.app.push_screen(panel)
        await pilot.pause()
        await pilot.press("l")
        panel.action_reset()
        await pilot.pause()
        screen = pilot.app.screen
        assert isinstance(screen, AliasEditPreviewModal)
        assert screen._op.kind == "unset"


async def test_action_edit_custom_alias_routes_to_custom_model_path(
    monkeypatch: Any,
) -> None:
    view = _view(
        "blogger",
        "user",
        configured=True,
        configured_value="claude/haiku",
        configured_source="custom",
    )
    _patch_views(monkeypatch, [view])
    monkeypatch.setattr(
        models_panel_edit, "plan_alias_edit", lambda *a, **k: _make_plan()
    )

    async with _TestApp().run_test() as pilot:
        panel = ModelsPanel()
        pilot.app.push_screen(panel)
        await pilot.pause()
        panel._pending_edit_view = view
        panel._on_edit_model_picked("claude/opus")
        await pilot.pause()
        assert isinstance(pilot.app.screen, DefaultEffortLevelModal)
        panel._on_edit_model_effort_picked(DefaultEffortLevelChoice(None))
        await pilot.pause()
        screen = pilot.app.screen
        assert isinstance(screen, AliasEditPreviewModal)
        assert screen._path == "llm_provider.model_aliases.custom.blogger.model"


async def test_action_reset_custom_alias_deletes_custom_entry(
    monkeypatch: Any,
) -> None:
    _patch_views(
        monkeypatch,
        [
            _view(
                "blogger",
                "user",
                configured=True,
                configured_value="claude/opus",
                configured_source="custom",
            )
        ],
    )
    monkeypatch.setattr(
        models_panel_edit, "plan_alias_edit", lambda *a, **k: _make_plan(op="unset")
    )

    async with _TestApp().run_test() as pilot:
        panel = ModelsPanel()
        pilot.app.push_screen(panel)
        await pilot.pause()
        await pilot.press("j")
        panel.action_reset()
        await pilot.pause()
        screen = pilot.app.screen
        assert isinstance(screen, AliasEditPreviewModal)
        assert screen._path == "llm_provider.model_aliases.custom.blogger"
        assert screen._reset_deletes_alias is True


# ---------------------------------------------------------------------------
# Panel — post-write handling & commit offer
# ---------------------------------------------------------------------------


def _outcome(op: str = "set") -> AliasEditOutcome:
    return AliasEditOutcome(
        alias="coder",
        applied=AppliedResult(
            path="/tmp/sase.yml",
            op=op,
            key_path=("llm_provider", "model_aliases", "builtin", "coder"),
            created=False,
            used_chezmoi=False,
        ),
    )


async def test_on_alias_edited_none_is_noop(monkeypatch: Any) -> None:
    _patch_views(monkeypatch, [_view("coder", "role")])
    offer_mock = MagicMock()
    monkeypatch.setattr(models_panel, "build_alias_commit_offer", offer_mock)

    async with _TestApp().run_test() as pilot:
        panel = ModelsPanel()
        pilot.app.push_screen(panel)
        await pilot.pause()
        panel.notify = MagicMock()  # type: ignore[method-assign]
        panel._on_alias_edited(None)
        await pilot.pause()
        panel.notify.assert_not_called()
        offer_mock.assert_not_called()


async def test_on_alias_edited_no_repo_skips_commit_offer(monkeypatch: Any) -> None:
    _patch_views(monkeypatch, [_view("coder", "role")])
    monkeypatch.setattr(models_panel, "build_alias_commit_offer", lambda *a, **k: None)

    async with _TestApp().run_test() as pilot:
        panel = ModelsPanel()
        pilot.app.push_screen(panel)
        await pilot.pause()
        panel.notify = MagicMock()  # type: ignore[method-assign]
        panel._pending_edit_raw_model = "@default@medium"
        panel._on_alias_edited(_outcome())
        await pilot.pause()
        # The panel stays on top — no commit-confirm modal pushed.
        assert isinstance(pilot.app.screen, ModelsPanel)
        panel.notify.assert_called_once_with("Updated @coder to @default@medium")


async def test_on_alias_edited_offers_commit_when_in_repo(monkeypatch: Any) -> None:
    _patch_views(monkeypatch, [_view("coder", "role")])
    offer = AliasCommitOffer(
        git_root="/repo",
        file_path="/repo/sase.yml",
        rel_path="sase.yml",
        message="chore: Update model alias @coder\n\nSASE_TYPE=config",
    )
    monkeypatch.setattr(models_panel, "build_alias_commit_offer", lambda *a, **k: offer)

    async with _TestApp().run_test() as pilot:
        panel = ModelsPanel()
        pilot.app.push_screen(panel)
        await pilot.pause()
        panel._on_alias_edited(_outcome())
        await _wait_for(pilot, lambda: isinstance(pilot.app.screen, ConfirmActionModal))
        modal = pilot.app.screen
        assert isinstance(modal, ConfirmActionModal)
        assert modal._title == "Commit & Push"
        assert modal._message == "Commit and push your model-alias change?"
        assert modal._subject == "sase.yml"
        assert modal._confirm_label == "Commit & push"
        assert modal._cancel_label == "Skip"
        assert modal._default == "confirm"


async def test_submit_commit_task_uses_app_queue(monkeypatch: Any) -> None:
    _patch_views(monkeypatch, [_view("coder", "role")])
    offer = AliasCommitOffer(
        git_root="/repo",
        file_path="/repo/sase.yml",
        rel_path="sase.yml",
        message="chore: Update model alias @coder\n\nSASE_TYPE=config",
    )

    async with _TestApp().run_test() as pilot:
        panel = ModelsPanel()
        pilot.app.push_screen(panel)
        await pilot.pause()
        submit = MagicMock()
        pilot.app._submit_tracked_task = submit  # type: ignore[attr-defined]
        panel._submit_commit_task(offer)
        await pilot.pause()
        submit.assert_called_once()
        args, kwargs = submit.call_args
        assert args[0] == "config-commit"
        assert kwargs["dedup_key"] == "config-commit:/repo:sase.yml"


# ---------------------------------------------------------------------------
# AliasEditPreviewModal — plan / preview / write
# ---------------------------------------------------------------------------


async def test_preview_modal_renders_plan(monkeypatch: Any) -> None:
    monkeypatch.setattr(
        models_panel_edit, "plan_alias_edit", lambda *a, **k: _make_plan()
    )

    async with _TestApp().run_test() as pilot:
        modal = AliasEditPreviewModal("coder", ConfigEditOp.set_value("opus"))
        pilot.app.push_screen(modal)
        await _wait_for(pilot, lambda: modal._plan is not None)
        # The preview Static is mounted and the rendered body reflects the plan.
        assert modal.query_one("#alias-edit-preview", Static) is not None
        text = modal._body_text().plain
        assert "coder" in text
        assert "opus" in text


async def test_preview_modal_confirm_writes_and_dismisses(monkeypatch: Any) -> None:
    monkeypatch.setattr(
        models_panel_edit, "plan_alias_edit", lambda *a, **k: _make_plan()
    )
    applied = AppliedResult(
        path="/tmp/sase.yml",
        op="set",
        key_path=("llm_provider", "model_aliases", "builtin", "coder"),
        created=False,
        used_chezmoi=False,
    )
    apply_mock = MagicMock(return_value=applied)
    monkeypatch.setattr(models_panel_edit, "apply_config_edit", apply_mock)
    result: list[Any] = []

    async with _TestApp().run_test() as pilot:
        modal = AliasEditPreviewModal("coder", ConfigEditOp.set_value("opus"))
        pilot.app.push_screen(modal, result.append)
        await _wait_for(pilot, lambda: modal._plan is not None)
        modal.action_confirm()
        await _wait_for(pilot, lambda: bool(result))

    apply_mock.assert_called_once()
    assert isinstance(result[0], AliasEditOutcome)
    assert result[0].alias == "coder"


async def test_preview_modal_chezmoi_applies_home_target_not_source(
    monkeypatch: Any,
) -> None:
    """A chezmoi-backed write runs ``chezmoi apply`` on the home target path.

    Regression: the modal previously handed the chezmoi *source* path to
    ``chezmoi apply``, which rejects it as "not in source state". The apply must
    receive the original home target (``plan.write_plan.file``).
    """
    home_target = "/home/u/.config/sase/sase.yml"
    source_path = "/home/u/.local/share/chezmoi/home/dot_config/sase/sase.yml"
    monkeypatch.setattr(
        models_panel_edit,
        "plan_alias_edit",
        lambda *a, **k: _make_plan(used_chezmoi=True, target_path=home_target),
    )
    applied = AppliedResult(
        path=source_path,
        op="set",
        key_path=("llm_provider", "model_aliases", "builtin", "coder"),
        created=False,
        used_chezmoi=True,
    )
    monkeypatch.setattr(
        models_panel_edit, "apply_config_edit", MagicMock(return_value=applied)
    )
    apply_chezmoi_mock = MagicMock(
        return_value=subprocess.CompletedProcess([], 0, stdout="", stderr="")
    )
    monkeypatch.setattr(models_panel_edit, "apply_chezmoi", apply_chezmoi_mock)
    result: list[Any] = []

    async with _TestApp().run_test() as pilot:
        modal = AliasEditPreviewModal("coder", ConfigEditOp.set_value("opus"))
        pilot.app.push_screen(modal, result.append)
        await _wait_for(pilot, lambda: modal._plan is not None)
        modal.action_confirm()
        await _wait_for(pilot, lambda: bool(result))

    apply_chezmoi_mock.assert_called_once_with(home_target)
    assert isinstance(result[0], AliasEditOutcome)


async def test_preview_modal_no_change_blocks_write(monkeypatch: Any) -> None:
    monkeypatch.setattr(
        models_panel_edit,
        "plan_alias_edit",
        lambda *a, **k: _make_plan(diff="   \n"),
    )
    apply_mock = MagicMock()
    monkeypatch.setattr(models_panel_edit, "apply_config_edit", apply_mock)

    async with _TestApp().run_test() as pilot:
        modal = AliasEditPreviewModal("coder", ConfigEditOp.set_value("opus"))
        pilot.app.push_screen(modal)
        await _wait_for(pilot, lambda: modal._plan is not None)
        modal.action_confirm()
        await pilot.pause()
        apply_mock.assert_not_called()
        assert modal._error is not None


async def test_preview_modal_cancel_dismisses_none(monkeypatch: Any) -> None:
    monkeypatch.setattr(
        models_panel_edit, "plan_alias_edit", lambda *a, **k: _make_plan()
    )
    result: list[Any] = []

    async with _TestApp().run_test() as pilot:
        modal = AliasEditPreviewModal("coder", ConfigEditOp.set_value("opus"))
        pilot.app.push_screen(modal, result.append)
        await _wait_for(pilot, lambda: modal._plan is not None)
        await pilot.press("escape")
        await _wait_for(pilot, lambda: bool(result))

    assert result[0] is None
