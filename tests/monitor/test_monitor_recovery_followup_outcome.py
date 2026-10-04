"""Recovery follow-up outcome persistence for host-completion settlement."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from sase.continuation_capture.rollout import (
    MONITOR_CONTINUATION_PROTOCOL_RECORDS_V1,
)
from sase.monitor._host_completion_shared import HostCompletionSettlement
from sase.monitor.output import OutputCapture
from sase.monitor.settlement import settle_claim_and_followup
from sase.turns.followup import FollowupLaunchResult
from tests.monitor._fixtures import make_starter_agent


@pytest.fixture(autouse=True)
def _sandbox_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / ".sase"))


@pytest.mark.parametrize(
    ("launch_result", "expected_outcome", "expected_degraded_reason"),
    [
        (
            FollowupLaunchResult(launched=True, agent_name="monitor--2"),
            "launched",
            None,
        ),
        (
            FollowupLaunchResult(
                launched=True,
                agent_name="monitor--2",
                degraded_reason="workspace unavailable",
            ),
            "launched-degraded",
            "workspace unavailable",
        ),
        (
            FollowupLaunchResult(launched=False, error="launch failed"),
            "not-launchable",
            None,
        ),
        (
            FollowupLaunchResult(
                launched=False,
                host_completed=True,
                agent_name="host-completion",
            ),
            "host-completed",
            None,
        ),
    ],
    ids=("launched", "launched-degraded", "not-launchable", "host-completed"),
)
def test_host_completion_recovery_records_followup_outcome(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    launch_result: FollowupLaunchResult,
    expected_outcome: str,
    expected_degraded_reason: str | None,
) -> None:
    import sase.monitor.settlement as settlement_module

    artifacts_dir = Path(
        make_starter_agent(
            "proj",
            "20261004120000",
            "monitor--mon",
            turn_kind="monitor",
            monitor_next_action="Continue after monitor recovery.",
            monitor_continuation_protocol=MONITOR_CONTINUATION_PROTOCOL_RECORDS_V1,
        )
    )
    meta_path = artifacts_dir / "agent_meta.json"
    meta: dict[str, Any] = json.loads(meta_path.read_text(encoding="utf-8"))
    meta["monitor_followup_error"] = "existing launch diagnostic"
    meta_path.write_text(json.dumps(meta), encoding="utf-8")

    def force_recovery(
        artifacts: str, current_meta: dict[str, Any], **kwargs: Any
    ) -> HostCompletionSettlement:
        launch_recovery = kwargs["launch_recovery"]
        if launch_result.host_completed:
            return HostCompletionSettlement(launch_result=launch_result)
        result = launch_recovery(
            artifacts,
            current_meta,
            monitor_state=kwargs["monitor_state"],
            exit_code=kwargs["exit_code"],
            elapsed_seconds=kwargs["elapsed_seconds"],
            capture=kwargs["capture"],
            project_name=kwargs["project_name"],
            timeout_kind=kwargs["timeout_kind"],
            transfer_from_pid=kwargs["transfer_from_pid"],
        )
        return HostCompletionSettlement(error=result.error, launch_result=result)

    monkeypatch.setattr(settlement_module, "settle_host_completion", force_recovery)
    monkeypatch.setattr(
        settlement_module, "_continuation_dispatch_blocked_reason", lambda _meta: None
    )
    monkeypatch.setattr(
        "sase.monitor.outcome_policy.settlement_policy_decision",
        lambda *_args, **_kwargs: {"action": "complete"},
    )

    def launch_followup(
        _artifacts: str, current_meta: dict[str, Any], **_kwargs: Any
    ) -> FollowupLaunchResult:
        if launch_result.launched:
            current_meta["monitor_followup_agent"] = launch_result.agent_name
        return launch_result

    result = settle_claim_and_followup(
        str(artifacts_dir),
        meta,
        monitor_state="completed",
        exit_code=0,
        elapsed_seconds=12,
        capture=OutputCapture(),
        timeout_kind=None,
        project_name="proj",
        launch_followup=launch_followup,
    )

    assert result.launch_result == launch_result
    persisted = json.loads(meta_path.read_text(encoding="utf-8"))
    assert persisted["monitor_followup_outcome"] == expected_outcome
    if expected_degraded_reason:
        assert persisted["monitor_followup_degraded_reason"] == expected_degraded_reason
    else:
        assert "monitor_followup_degraded_reason" not in persisted
    assert persisted["monitor_followup_error"] == "existing launch diagnostic"
