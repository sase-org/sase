"""Focused tests for the reusable family-shell substrate."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from sase.agent.pending_handoff import MONITOR_PENDING_MARKER
from sase.gate_shell.settlement import _done_marker
from sase.shells.followup import (
    FollowupLaunchResult,
    FollowupPersistence,
    fork_target_for_settled_starter,
    record_followup_launched,
)
from sase.shells.handoff import (
    will_handoff_shell_to_agent_runner,
    write_shell_pending_marker,
)
from sase.shells.member import create_family_shell_member
from sase.shells.naming import SequenceSuffixSpec, allocate_shell_suffix
from sase.shells.settlement import (
    ShellSettlementConfig,
    settle_shell_claim_and_followup,
    stamp_shell_finished_at,
)
from sase.shells.state import (
    ShellStateConfig,
    is_real_shell_member,
    is_shell_member_role,
    shell_state_bucket,
    shell_state_is_terminal,
)
from sase.shells.status import (
    ShellStatusPair,
    effective_shell_status,
    shell_status_pair,
    shell_status_style,
)


@pytest.fixture(autouse=True)
def _sandbox_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / ".sase"))


def test_create_family_shell_member_layers_kind_role_and_metadata() -> None:
    artifacts_dir = create_family_shell_member(
        "proj",
        {
            "name": "acme--0",
            "agent_family": "acme",
            "model": "claude-sonnet-5",
            "workspace_dir": "/work/acme",
            "agent_clan": "clan-a",
            "vcs_ref": ["git", "home"],
        },
        family="acme",
        suffix="--gate",
        prev_artifacts_timestamp="20260812120000",
        workspace_num=3,
        shell_kind="proc",
        family_role="gate",
        metadata={"gate_id": "g123", "pid": None},
        inherited_metadata_fields=("agent_clan",),
    )

    meta = json.loads((Path(artifacts_dir) / "agent_meta.json").read_text())
    assert meta["name"] == "acme--gate"
    assert meta["workflow_name"] == "acme"
    assert meta["agent_family"] == "acme"
    assert meta["agent_family_role"] == "gate"
    assert meta["role_suffix"] == "--gate"
    assert meta["parent_timestamp"] == "20260812120000"
    assert meta["workspace_num"] == 3
    assert meta["shell_kind"] == "proc"
    assert meta["gate_id"] == "g123"
    assert meta["pid"] is None
    assert meta["model"] == "claude-sonnet-5"
    assert meta["workspace_dir"] == "/work/acme"
    assert meta["agent_clan"] == "clan-a"
    assert meta["vcs_ref"] == ["git", "home"]


def test_allocate_shell_suffix_uses_first_suffix_then_template_allocator() -> None:
    spec = SequenceSuffixSpec(first_suffix="--gate", sequence_template="--gate-@")

    assert (
        allocate_shell_suffix(
            "acme",
            has_existing_shell=False,
            spec=spec,
        )
        == "--gate"
    )
    assert (
        allocate_shell_suffix(
            "acme",
            has_existing_shell=True,
            spec=spec,
            allocator=lambda lane, template: f"{template.removesuffix('@')}7",
        )
        == "--gate-7"
    )


def test_write_shell_pending_marker_adds_payload_and_refresh_pulse(
    tmp_path: Path,
) -> None:
    artifacts_dir = tmp_path / "artifacts" / "ace-run" / "202608" / "12"
    artifacts_dir.mkdir(parents=True)

    marker = write_shell_pending_marker(
        MONITOR_PENDING_MARKER,
        {"shell_id": "s123", "member_agent_name": "acme--gate"},
        str(artifacts_dir),
        timestamp=123.0,
    )

    assert json.loads(marker.read_text(encoding="utf-8")) == {
        "shell_id": "s123",
        "member_agent_name": "acme--gate",
        "timestamp": 123.0,
    }
    assert (tmp_path / "artifacts" / "ace-run" / ".ace_refresh_pulse").exists()
    assert will_handoff_shell_to_agent_runner({"SASE_AGENT": "1"}) is True
    assert will_handoff_shell_to_agent_runner({}) is False


def test_status_and_state_helpers_are_parameterized() -> None:
    state = ShellStateConfig(
        family_role="gate",
        buckets={"running": "Running", "approved": "Done", "rejected": "Failed"},
    )
    pair = shell_status_pair(
        " OPEN ",
        "CLOSED",
        default_start="OPEN",
        default_stop="CLOSED",
        max_chars=20,
        ellipsis="...",
    )

    assert isinstance(pair, ShellStatusPair)
    assert pair.start == "OPEN"
    assert shell_state_bucket("approved", state) == "Done"
    assert shell_state_is_terminal("approved", state) is True
    assert shell_state_is_terminal("running", state) is False
    assert is_shell_member_role("gate", config=state) is True
    assert is_shell_member_role(None, "--mon", config=state) is False
    assert is_real_shell_member("gate", "g123", config=state) is True
    assert (
        shell_status_style(
            pair,
            shell_state="running",
            accents=("#00D7AF",),
            failure_states={"rejected"},
            settled_ok_states={"approved"},
            failure_style="bold red",
        )
        == "bold #00D7AF"
    )
    assert (
        effective_shell_status(
            pair,
            shell_state="approved",
            settled=False,
            terminal_states={"approved", "rejected"},
        )
        == "CLOSED"
    )


def test_fork_target_prefers_the_family_transcript() -> None:
    assert (
        fork_target_for_settled_starter(
            starter_name="acme--code",
            family_name="acme",
            settled=True,
        )
        == "acme"
    )
    assert (
        fork_target_for_settled_starter(
            starter_name="acme--code",
            family_name=None,
            settled=True,
        )
        == "acme"
    )
    assert (
        fork_target_for_settled_starter(
            starter_name="acme--code",
            family_name="acme",
            settled=False,
        )
        is None
    )


def test_settle_shell_claim_and_followup_uses_configured_fields() -> None:
    config = ShellSettlementConfig(
        next_action_field="gate_next_action",
        agent_field="gate_followup_agent",
        outcome_field="gate_followup_outcome",
        error_field="gate_followup_error",
        degraded_reason_field="gate_followup_degraded_reason",
        prompt_path_field="gate_followup_prompt_path",
        lost_state="lost",
        stopped_state="stopped",
        lost_followup_error="lost gate",
        degraded_outcome="launched-degraded",
        fallback_followup_error="follow-up failed",
        missing_project_error="missing project",
    )
    meta: dict[str, Any] = {"gate_next_action": "continue"}
    updated: dict[str, Any] = {}
    releases: list[tuple[dict[str, Any], str | None]] = []

    def update_meta_field(_artifacts_dir: str, key: str, value: Any) -> None:
        updated[key] = value

    def release_claim(
        release_meta: dict[str, Any],
        project_name: str | None,
    ) -> str | None:
        releases.append((release_meta, project_name))
        return None

    result = settle_shell_claim_and_followup(
        "/tmp/artifacts",
        meta,
        shell_state="completed",
        project_name="proj",
        config=config,
        release_claim=release_claim,
        launch_followup=lambda *_args, **_kwargs: FollowupLaunchResult(
            launched=True,
            degraded_reason="fresh claim",
            agent_name="acme--1",
        ),
        launch_kwargs={},
        update_meta_field=update_meta_field,
    )

    assert result is None
    assert releases == [(meta, "proj")]
    assert meta["gate_followup_outcome"] == "launched-degraded"
    assert meta["gate_followup_degraded_reason"] == "fresh claim"
    assert updated["gate_followup_outcome"] == "launched-degraded"
    assert updated["gate_followup_degraded_reason"] == "fresh claim"


def test_record_followup_launched_uses_configured_agent_field() -> None:
    meta: dict[str, object] = {}
    updated: dict[str, object] = {}

    result = record_followup_launched(
        "/tmp/artifacts",
        meta,
        agent_name="acme--1",
        degraded_reason=None,
        persistence=FollowupPersistence(
            agent_field="shell_followup_agent",
            error_field="shell_followup_error",
            prompt_path_field="shell_followup_prompt_path",
            degraded_reason_field="shell_followup_degraded_reason",
            prompt_filename="prompt.md",
            prompt_label="Prompt",
        ),
        update_meta_field=lambda _path, key, value: updated.__setitem__(key, value),
    )

    assert result.launched is True
    assert meta["shell_followup_agent"] == "acme--1"
    assert updated["shell_followup_agent"] == "acme--1"


_REPO_ROOT = Path(__file__).resolve().parents[2]
_KNOWN_SHELL_DONE_WRITERS = frozenset(
    {
        "src/sase/monitor/supervise.py",
        "src/sase/monitor/proc_adapter.py",
        "src/sase/monitor/reconcile.py",
        "src/sase/monitor/start.py",
        "src/sase/gate_shell/settlement.py",
    }
)


def test_stamp_shell_finished_at_records_a_numeric_instant(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("sase.shells.settlement.time.time", lambda: 1_779_999_999.5)
    marker: dict[str, Any] = {"outcome": "monitored"}

    stamp_shell_finished_at(marker)

    assert marker["finished_at"] == 1_779_999_999.5


def test_gate_done_marker_stamps_finished_at_through_shared_helper(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("sase.shells.settlement.time.time", lambda: 1_779_999_999.5)

    marker = _done_marker({"artifacts_dir": ""}, gate_state="answered", reason=None)

    assert marker["finished_at"] == 1_779_999_999.5
    assert marker["outcome"] == "gated"


def test_shell_done_marker_writers_stamp_finished_at_through_shared_helper() -> None:
    found: set[str] = set()
    missing: list[str] = []
    for root in (
        _REPO_ROOT / "src" / "sase" / "monitor",
        _REPO_ROOT / "src" / "sase" / "gate_shell",
    ):
        for path in sorted(root.rglob("*.py")):
            source = path.read_text(encoding="utf-8")
            if "write_done_marker_and_update_index(" not in source:
                continue
            relative = path.relative_to(_REPO_ROOT).as_posix()
            found.add(relative)
            if "stamp_shell_finished_at(" not in source:
                missing.append(relative)

    assert _KNOWN_SHELL_DONE_WRITERS <= found, (
        "expected shell done-marker writers were missing: "
        f"{sorted(_KNOWN_SHELL_DONE_WRITERS - found)}"
    )
    assert missing == [], (
        "done-marker writers must stamp finished_at via "
        f"stamp_shell_finished_at: {missing}"
    )
