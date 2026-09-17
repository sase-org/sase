"""Tests for launch-carried ``%hold`` primitives in ``sase.agent.launch_hold``."""

from __future__ import annotations

import os
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from sase.agent.launch_hold import (
    LAUNCH_HOLD_RELEASE_REASON,
    LaunchHoldError,
    _arm_hold_for_fields,
    _hold_fields_for,
    _launch_unit_armer,
    _runner_anchor_armer,
    arm_bootstrap_hold,
    rebind_hold,
    release_hold_best_effort,
    unit_hold_key,
)
from sase.core.agent_hold_facade import list_current_agent_holds
from sase.core.agent_launch_wire_records import (
    AgentUnitWire,
    HoldFieldsWire,
    LaunchUnitWire,
    ProcUnitWire,
)
from sase.xprompt.code_value import CodeValue
from sase.xprompt.hold_directive import HoldFields


def _launch_armer(**overrides: object) -> dict[str, object]:
    armer: dict[str, object] = {
        "kind": "launch",
        "key": "launch:req1/u1",
        "display": "planner (launch req1)",
        "project": "scratch",
        "agent_name": "planner",
        "family": None,
        "clan": None,
        "pid": os.getpid(),
        "done_marker_path": "/tmp/does-not-exist/receipt.json",
    }
    armer.update(overrides)
    return armer


def test_unit_hold_key_format() -> None:
    assert unit_hold_key("req1", "u1") == "launch:req1/u1"


def test_hold_fields_for_reads_hold_fields_wire_from_dataclass_payload() -> None:
    payload = AgentUnitWire(prompt="hi", hold=HoldFieldsWire(names=["a"], future=True))

    fields = _hold_fields_for(payload)

    assert fields == HoldFields(names=("a",), future=True)


def test_hold_fields_for_reads_directive_mapping() -> None:
    payload = {"hold": {"names": ["b"], "pending": True}}

    fields = _hold_fields_for(payload)

    assert fields == HoldFields(names=("b",), pending=True)


def test_hold_fields_for_returns_none_without_hold() -> None:
    assert _hold_fields_for(AgentUnitWire(prompt="hi")) is None
    assert _hold_fields_for({}) is None


def test_arm_hold_for_fields_arms_and_returns_result() -> None:
    armer = _launch_armer()
    fields = HoldFields(future=True)

    result = _arm_hold_for_fields(fields, armer=armer)

    assert result.record["armer"]["kind"] == "launch"
    assert result.record["selectors"]["future"] is True


def test_arm_hold_for_fields_wraps_errors_with_hold_prefix() -> None:
    armer = _launch_armer()
    fields = HoldFields()  # no selector -> the Rust arm call rejects it.

    with pytest.raises(LaunchHoldError, match=r"^%hold: "):
        _arm_hold_for_fields(fields, armer=armer)


def test_rebind_hold_returns_none_for_missing_key() -> None:
    assert rebind_hold("launch:does-not-exist/u1", _launch_armer()) is None


def test_rebind_hold_round_trips_an_armed_record() -> None:
    armer = _launch_armer(key="launch:req2/u1")
    result = _arm_hold_for_fields(HoldFields(future=True), armer=armer)
    old_key = result.record["armer"]["key"]

    new_armer = dict(armer)
    new_armer["pid"] = os.getpid() + 1
    rebound = rebind_hold(old_key, new_armer)

    assert rebound is not None
    assert rebound["armer"]["pid"] == os.getpid() + 1


def test_rebind_hold_wraps_kin_rejection_with_hold_prefix() -> None:
    armer = _launch_armer(key="launch:req3/u1", agent_name="not-foo")
    result = _arm_hold_for_fields(HoldFields(names=("foo",)), armer=armer)
    old_key = result.record["armer"]["key"]

    kin_armer = dict(armer)
    kin_armer["agent_name"] = "foo"

    with pytest.raises(LaunchHoldError, match=r"^%hold: "):
        rebind_hold(old_key, kin_armer)


def test_release_hold_best_effort_returns_true_on_success() -> None:
    armer = _launch_armer(key="launch:req4/u1")
    result = _arm_hold_for_fields(HoldFields(future=True), armer=armer)
    key = result.record["armer"]["key"]

    assert release_hold_best_effort(key, reason=LAUNCH_HOLD_RELEASE_REASON) is True
    assert list_current_agent_holds() == []


def test_release_hold_best_effort_swallows_store_error() -> None:
    with patch(
        "sase.core.agent_hold_facade.release_agent_hold",
        side_effect=RuntimeError("boom"),
    ):
        assert release_hold_best_effort("launch:req5/u1", reason="cleanup") is False


def test_launch_unit_armer_for_agent_unit_sets_identity() -> None:
    unit = LaunchUnitWire(
        logical_id="u1",
        source_order=0,
        payload=AgentUnitWire(
            prompt="hello",
            identity="planner",
            identity_explicit=True,
            family_attach_parent="fam",
            clan="clanX",
        ),
    )

    armer = _launch_unit_armer(
        unit,
        request_id="req6",
        project="proj1",
        pid=4242,
        done_marker_path="/tmp/receipt.json",
    )

    assert armer["kind"] == "launch"
    assert armer["key"] == "launch:req6/u1"
    assert armer["agent_name"] == "clanX.planner"
    assert armer["family"] == "fam"
    assert armer["clan"] == "clanX"
    assert armer["pid"] == 4242
    assert armer["done_marker_path"] == "/tmp/receipt.json"


def test_launch_unit_armer_for_proc_unit_sets_no_identity() -> None:
    unit = LaunchUnitWire(
        logical_id="p1",
        source_order=0,
        payload=ProcUnitWire(
            code=CodeValue(
                source="echo hi",
                language="bash",
                digest="d",
                preview="echo hi",
                info_string=None,
            ),
            shell_name="myshell",
        ),
    )

    armer = _launch_unit_armer(
        unit,
        request_id="req7",
        project="proj1",
        pid=4242,
        done_marker_path="/tmp/receipt.json",
    )

    assert armer["kind"] == "launch"
    assert armer["key"] == "launch:req7/p1"
    assert armer["agent_name"] is None
    assert armer["family"] is None
    assert armer["clan"] is None
    assert armer["display"].startswith("myshell")


def test_runner_anchor_armer_replaces_pid_and_done_marker_path() -> None:
    armer = _launch_armer()

    anchored = _runner_anchor_armer(armer, pid=555, artifacts_dir="/a/artifacts")

    assert anchored["pid"] == 555
    assert anchored["done_marker_path"] == "/a/artifacts/done.json"
    assert anchored["key"] == armer["key"]
    assert armer["pid"] != 555


def test_arm_bootstrap_hold_arms_fresh_agent_hold() -> None:
    state = SimpleNamespace(artifacts_dir="/tmp/artifacts")
    info = SimpleNamespace(hold=HoldFields(future=True))
    armer = {"kind": "agent", "key": "agent:planner"}

    with (
        patch("sase.xprompt.hold_directive.agent_holds_enabled", return_value=True),
        patch(
            "sase.core.agent_hold_facade.agent_armer_wire_for_artifacts",
            return_value=armer,
        ) as armer_for_artifacts,
        patch("sase.agent.launch_hold._arm_hold_for_fields") as arm,
        patch("sase.agent.launch_hold.rebind_hold") as rebind,
    ):
        arm_bootstrap_hold(state, info, None, None)

    armer_for_artifacts.assert_called_once_with(
        "/tmp/artifacts",
        pid_fallback=os.getpid(),
    )
    arm.assert_called_once_with(info.hold, armer=armer)
    rebind.assert_not_called()


def test_arm_bootstrap_hold_rebinds_prearmed_key() -> None:
    state = SimpleNamespace(artifacts_dir="/tmp/artifacts")
    info = SimpleNamespace(hold=HoldFields(future=True))
    armer = {"kind": "agent", "key": "agent:planner"}

    with (
        patch("sase.xprompt.hold_directive.agent_holds_enabled", return_value=True),
        patch(
            "sase.core.agent_hold_facade.agent_armer_wire_for_artifacts",
            return_value=armer,
        ),
        patch(
            "sase.agent.launch_hold.rebind_hold", return_value={"armer": armer}
        ) as rebind,
        patch("sase.agent.launch_hold._arm_hold_for_fields") as arm,
    ):
        arm_bootstrap_hold(state, info, None, "launch:req/u1")

    rebind.assert_called_once_with("launch:req/u1", armer)
    arm.assert_not_called()


def test_arm_bootstrap_hold_releases_key_when_no_hold_was_parsed() -> None:
    state = SimpleNamespace(artifacts_dir="/tmp/artifacts")
    info = SimpleNamespace(hold=None)

    with (
        patch("sase.xprompt.hold_directive.agent_holds_enabled", return_value=True),
        patch("sase.agent.launch_hold.release_hold_best_effort") as release,
    ):
        arm_bootstrap_hold(state, info, None, "launch:req/u1")

    release.assert_called_once_with(
        "launch:req/u1",
        reason="launch hold key had no hold directive",
        display="launch:req/u1",
    )


def test_arm_bootstrap_hold_releases_key_when_rebind_fails() -> None:
    state = SimpleNamespace(artifacts_dir="/tmp/artifacts")
    info = SimpleNamespace(hold=HoldFields(future=True))
    armer = {"kind": "agent", "key": "agent:planner"}

    with (
        patch("sase.xprompt.hold_directive.agent_holds_enabled", return_value=True),
        patch(
            "sase.core.agent_hold_facade.agent_armer_wire_for_artifacts",
            return_value=armer,
        ),
        patch(
            "sase.agent.launch_hold.rebind_hold",
            side_effect=LaunchHoldError("%hold: boom"),
        ),
        patch("sase.agent.launch_hold.release_hold_best_effort") as release,
    ):
        with pytest.raises(LaunchHoldError, match=r"^%hold: boom"):
            arm_bootstrap_hold(state, info, None, "launch:req/u1")

    release.assert_called_once_with(
        "launch:req/u1",
        reason="launch hold rebind failed",
        display="launch:req/u1",
    )


def test_arm_bootstrap_hold_skips_refresh_pass(monkeypatch: pytest.MonkeyPatch) -> None:
    from sase.axe.run_agent_runner_refresh import RUNNER_CODE_REFRESHED_ENV

    monkeypatch.setenv(RUNNER_CODE_REFRESHED_ENV, "1")
    state = SimpleNamespace(artifacts_dir="/tmp/artifacts")
    info = SimpleNamespace(hold=HoldFields(future=True))

    with (
        patch("sase.xprompt.hold_directive.agent_holds_enabled", return_value=True),
        patch(
            "sase.core.agent_hold_facade.agent_armer_wire_for_artifacts"
        ) as armer_for_artifacts,
    ):
        arm_bootstrap_hold(state, info, None, "launch:req/u1")

    armer_for_artifacts.assert_not_called()


def test_arm_bootstrap_hold_skips_retry_handoff() -> None:
    state = SimpleNamespace(artifacts_dir="/tmp/artifacts")
    info = SimpleNamespace(hold=HoldFields(future=True))

    with (
        patch("sase.xprompt.hold_directive.agent_holds_enabled", return_value=True),
        patch(
            "sase.core.agent_hold_facade.agent_armer_wire_for_artifacts"
        ) as armer_for_artifacts,
    ):
        arm_bootstrap_hold(state, info, object(), "launch:req/u1")

    armer_for_artifacts.assert_not_called()


def test_arm_bootstrap_hold_skips_when_flag_disabled() -> None:
    state = SimpleNamespace(artifacts_dir="/tmp/artifacts")
    info = SimpleNamespace(hold=HoldFields(future=True))

    with (
        patch("sase.xprompt.hold_directive.agent_holds_enabled", return_value=False),
        patch(
            "sase.core.agent_hold_facade.agent_armer_wire_for_artifacts"
        ) as armer_for_artifacts,
    ):
        arm_bootstrap_hold(state, info, None, "launch:req/u1")

    armer_for_artifacts.assert_not_called()
