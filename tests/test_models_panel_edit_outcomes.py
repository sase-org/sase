"""Tests for Models panel post-edit handling and commit offers."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import sase.ace.tui.modals.models_panel as models_panel
from sase.ace.tui.modals.confirm_action_modal import ConfirmActionModal
from sase.ace.tui.modals.models_panel import ModelsPanel
from sase.ace.tui.modals.models_panel_edit_helpers import (
    AliasCommitOffer,
    AliasEditOutcome,
)
from sase.config import AppliedResult
from tests._models_panel_helpers import (
    ModelsPanelTestApp,
    make_alias_view,
    patch_alias_views,
    wait_for,
)


def _outcome(op: str = "set") -> AliasEditOutcome:
    return AliasEditOutcome(
        alias="medium_phase_worker",
        applied=AppliedResult(
            path="/tmp/sase.yml",
            op=op,
            key_path=(
                "llm_provider",
                "model_aliases",
                "builtin",
                "medium_phase_worker",
            ),
            created=False,
            used_chezmoi=False,
        ),
    )


async def test_on_alias_edited_none_is_noop(monkeypatch: Any) -> None:
    patch_alias_views(monkeypatch, [make_alias_view("medium_phase_worker", "role")])
    offer_mock = MagicMock()
    monkeypatch.setattr(models_panel, "build_alias_commit_offer", offer_mock)

    async with ModelsPanelTestApp().run_test() as pilot:
        panel = ModelsPanel()
        pilot.app.push_screen(panel)
        await pilot.pause()
        panel.notify = MagicMock()  # type: ignore[method-assign]
        panel._on_alias_edited(None)
        await pilot.pause()
        panel.notify.assert_not_called()
        offer_mock.assert_not_called()


async def test_on_alias_edited_no_repo_skips_commit_offer(monkeypatch: Any) -> None:
    patch_alias_views(monkeypatch, [make_alias_view("medium_phase_worker", "role")])
    monkeypatch.setattr(models_panel, "build_alias_commit_offer", lambda *a, **k: None)

    async with ModelsPanelTestApp().run_test() as pilot:
        panel = ModelsPanel()
        pilot.app.push_screen(panel)
        await pilot.pause()
        panel.notify = MagicMock()  # type: ignore[method-assign]
        panel._pending_edit_raw_model = "@default@medium"
        panel._on_alias_edited(_outcome())
        await pilot.pause()
        # The panel stays on top — no commit-confirm modal pushed.
        assert isinstance(pilot.app.screen, ModelsPanel)
        panel.notify.assert_called_once_with(
            "Updated @medium_phase_worker to @default@medium"
        )


async def test_on_alias_edited_offers_commit_when_in_repo(monkeypatch: Any) -> None:
    patch_alias_views(monkeypatch, [make_alias_view("medium_phase_worker", "role")])
    offer = AliasCommitOffer(
        git_root="/repo",
        file_path="/repo/sase.yml",
        rel_path="sase.yml",
        message="chore: Update model alias @medium_phase_worker\n\nSASE_TYPE=config",
    )
    monkeypatch.setattr(models_panel, "build_alias_commit_offer", lambda *a, **k: offer)

    async with ModelsPanelTestApp().run_test() as pilot:
        panel = ModelsPanel()
        pilot.app.push_screen(panel)
        await pilot.pause()
        panel._on_alias_edited(_outcome())
        await wait_for(pilot, lambda: isinstance(pilot.app.screen, ConfirmActionModal))
        modal = pilot.app.screen
        assert isinstance(modal, ConfirmActionModal)
        assert modal._title == "Commit & Push"
        assert modal._message == "Commit and push your model-alias change?"
        assert modal._subject == "sase.yml"
        assert modal._confirm_label == "Commit & push"
        assert modal._cancel_label == "Skip"
        assert modal._default == "confirm"


async def test_submit_commit_task_uses_app_queue(monkeypatch: Any) -> None:
    patch_alias_views(monkeypatch, [make_alias_view("medium_phase_worker", "role")])
    offer = AliasCommitOffer(
        git_root="/repo",
        file_path="/repo/sase.yml",
        rel_path="sase.yml",
        message="chore: Update model alias @medium_phase_worker\n\nSASE_TYPE=config",
    )

    async with ModelsPanelTestApp().run_test() as pilot:
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
