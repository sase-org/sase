"""ACE provider-drain prompt panel rows and key decisions."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

from sase.ace.tui.modals.provider_drain_prompt_modal import (
    ProviderDrainPromptDecision,
    ProviderDrainPromptModal,
)
from sase.agent.provider_drain import (
    DrainRoute,
    ProviderDrainMove,
    ProviderDrainPlan,
    ProviderDrainSkip,
)
from tests._models_panel_provider_routing_helpers import disable


def _move(
    name: str,
    *,
    target_provider: str,
    target_model: str = "gpt-5",
) -> ProviderDrainMove:
    return ProviderDrainMove(
        name=name,
        presented_name=name,
        project="sase",
        status="RUNNING",
        route=DrainRoute(
            kind="reroute",
            target_provider=target_provider,
            target_model=target_model,
        ),
        restart_plan=SimpleNamespace(),  # type: ignore[arg-type]
    )


def _plan(
    *,
    moves: tuple[ProviderDrainMove, ...] = (),
    skips: tuple[ProviderDrainSkip, ...] = (),
) -> ProviderDrainPlan:
    return ProviderDrainPlan(
        provider="claude",
        disable=disable("claude", expires_at=4_000.0, source="ace"),
        moves=moves,
        skips=skips,
        model_override=None,
        limit=20,
    )


def test_prompt_rows_include_default_model_pick_and_leave_actions() -> None:
    plan = _plan(
        moves=(
            _move("sase-aa", target_provider="codex"),
            _move("sase-bb", target_provider="gemini"),
        ),
        skips=(
            ProviderDrainSkip(
                name="sase-cc",
                presented_name="sase-cc",
                status="RUNNING",
                reason="stranded",
                detail="pinned to claude/opus; not reachable",
            ),
        ),
    )

    modal = ProviderDrainPromptModal(plan, now=100.0)

    rows = {row.key: row for row in modal._rows}
    assert list(rows) == ["r", "m", "l"]
    assert rows["r"].title == "Relaunch 2 agents now"
    assert "1 to CODEX" in rows["r"].subtitle
    assert "1 to GEMINI" in rows["r"].subtitle
    assert rows["m"].title == "Relaunch them on a model I pick..."
    assert rows["l"].subtitle == "1 pinned to claude/opus cannot move either way"


def test_prompt_omits_default_relaunch_when_only_model_override_can_help() -> None:
    plan = _plan(
        skips=(
            ProviderDrainSkip(
                name="sase-cc",
                presented_name="sase-cc",
                status="RUNNING",
                reason="stranded",
                detail="pinned to claude/opus; not reachable",
            ),
        )
    )

    modal = ProviderDrainPromptModal(plan, now=100.0)

    assert [row.key for row in modal._rows] == ["m", "l"]


def test_prompt_key_actions_dismiss_expected_decisions() -> None:
    modal = ProviderDrainPromptModal(
        _plan(moves=(_move("sase-aa", target_provider="codex"),)),
        now=100.0,
    )
    modal.dismiss = MagicMock()  # type: ignore[method-assign]

    modal.action_relaunch()
    modal.action_pick_model()
    modal.action_leave()

    assert [call.args[0] for call in modal.dismiss.call_args_list] == [
        ProviderDrainPromptDecision(action="relaunch"),
        ProviderDrainPromptDecision(action="pick_model"),
        ProviderDrainPromptDecision(action="leave"),
    ]
