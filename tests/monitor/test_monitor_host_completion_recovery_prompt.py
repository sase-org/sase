"""Recovery reasons persist in the receipt/meta and render in follow-ups."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

from sase.monitor.delivery import load_host_completion_receipt
from sase.monitor.followup_prompt import compose_followup_prompt
from sase.monitor.host_completion_complete import recover_host_completion
from sase.monitor.host_completion_state import RECOVERY_STATUS
from sase.monitor.output import OutputCapture
from sase.turns.followup import FollowupLaunchResult

from ._followup_prompt_fixtures import _COMMON, _assert_inside_any_region


def _recovery_kwargs(*, reasons: list[str]) -> dict[str, Any]:
    return {
        "starter_name": "acme--0",
        "monitor_state": "completed",
        "exit_code": 0,
        "elapsed_seconds": 42.0,
        "timeout_seconds": 2700.0,
        "host_completion_status": RECOVERY_STATUS,
        "host_completion_reason": reasons[0],
        "host_completion_reasons": reasons,
    }


def test_recovered_completed_check_renders_host_completion_section() -> None:
    prompt = compose_followup_prompt(
        **_COMMON,
        **_recovery_kwargs(
            reasons=[
                "missing_required_stage:formatting",
                "stale_worktree_fingerprint",
            ]
        ),
    )
    section_start = prompt.index("## Host completion")
    next_action_start = prompt.index("## Your next action")
    assert section_start < next_action_start
    assert "but host completion did not land the change" in prompt
    assert "`missing_required_stage:formatting`" in prompt
    assert "`stale_worktree_fingerprint`" in prompt
    # Stage gloss tells the follow-up not to re-run the same check.
    assert "re-running the same check cannot fix this" in prompt
    assert "sase final submit" in prompt
    _assert_inside_any_region(prompt, "## Host completion")


def test_non_recovery_followup_renders_no_host_completion_section() -> None:
    prompt = compose_followup_prompt(
        starter_name="acme--0",
        monitor_state="completed",
        exit_code=0,
        elapsed_seconds=42.0,
        timeout_seconds=2700.0,
        **_COMMON,
    )
    assert "## Host completion" not in prompt


def test_recover_persists_full_reasons_in_receipt_and_meta(
    tmp_path: Any, monkeypatch: Any
) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / ".sase"))
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    (artifacts / "agent_meta.json").write_text("{}", encoding="utf-8")
    meta: dict[str, Any] = {"monitor_id": "m1"}
    reasons = ["missing_required_stage:formatting", "stale_worktree_fingerprint"]

    def _launch_recovery(*args: Any, **kwargs: Any) -> FollowupLaunchResult:
        return FollowupLaunchResult(launched=False)

    settlement = recover_host_completion(
        str(artifacts),
        meta,
        intent_root=str(artifacts),
        completion_ref="cci:missing",
        reason=reasons[0],
        reasons=reasons,
        launch_recovery=_launch_recovery,  # type: ignore[arg-type]
        release_claim=lambda m, p: None,
        project_name="proj",
        record={},
        monitor_state="completed",
        exit_code=0,
        elapsed_seconds=42.0,
        capture=MagicMock(spec=OutputCapture),
    )
    assert settlement is not None
    receipt = load_host_completion_receipt(str(artifacts))
    assert receipt is not None
    assert receipt["status"] == RECOVERY_STATUS
    assert receipt["reason"] == reasons[0]
    assert receipt["reasons"] == reasons
    assert meta["monitor_host_completion_status"] == RECOVERY_STATUS
    assert meta["monitor_host_completion_reason"] == reasons[0]
    assert meta["monitor_host_completion_reasons"] == reasons


def test_unknown_recovery_code_renders_bare() -> None:
    prompt = compose_followup_prompt(
        **_COMMON,
        **_recovery_kwargs(reasons=["some_future_reason"]),
    )
    assert "`some_future_reason`" in prompt
