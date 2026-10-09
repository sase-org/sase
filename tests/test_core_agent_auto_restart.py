"""Parity tests for the Rust-backed auto-restart facade."""

from __future__ import annotations

import pytest

from sase.core.agent_auto_restart_facade import (
    advance_auto_restart_ledger,
    auto_restart_lineage_root,
    auto_restart_recovery_is_in_flight,
    auto_restart_wire_schema_version,
    claim_auto_restart_ledger,
    classify_agent_failure,
    derive_auto_restart_episode,
)
from sase.core.agent_auto_restart_wire import (
    AGENT_AUTO_RESTART_WIRE_SCHEMA_VERSION,
    AutoRestartContextWire,
    AutoRestartWitnessesWire,
)
from sase.core.agent_scan_wire_markers import DoneMarkerWire
from sase.core.agent_scan_wire_conversion import (
    _done_marker_from_dict as done_marker_from_dict,
)

from ._rust_extension_module_helpers import install_fake_rust_extension


def _context() -> AutoRestartContextWire:
    return AutoRestartContextWire(
        lifecycle_phase="waiting",
        error_text=(
            "ImportError: cannot import name 'auto_launch_prefix' from "
            "'sase.monitor.continuation_delivery'"
        ),
        log_tail="Refreshing sase runner code after dependency wait",
    )


def _witnesses() -> AutoRestartWitnessesWire:
    return AutoRestartWitnessesWire(
        boot_identity="sase@9c5000f",
        current_identity="sase@9fd8a08",
    )


def test_wire_schema_mirror_matches_core() -> None:
    assert AGENT_AUTO_RESTART_WIRE_SCHEMA_VERSION == 1


def test_facade_classify_calls_rust_binding(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[object, object, object]] = []

    def fake_classify(
        facts: object, context: object, witnesses: object
    ) -> dict[str, object]:
        calls.append((facts, context, witnesses))
        return {
            "schema_version": AGENT_AUTO_RESTART_WIRE_SCHEMA_VERSION,
            "tier": "tier1_torn_python",
            "family": "cannot_import_name",
            "signature": "ImportError: cannot import name",
            "origin_module": "sase.monitor.continuation_delivery",
            "missing_symbol": "auto_launch_prefix",
            "phase_class": "pre_provider",
            "mode": "defer",
            "reason": "probe_pending",
            "reason_text": "waiting for the fresh-interpreter probe",
            "witnesses_fired": ["W1", "W2"],
            "episode_id": "sase@9fd8a08",
        }

    install_fake_rust_extension(monkeypatch, classify_agent_failure=fake_classify)

    verdict = classify_agent_failure(_context(), _witnesses())

    assert verdict.mode == "defer"
    assert verdict.missing_symbol == "auto_launch_prefix"
    assert verdict.witnesses_fired == ("W1", "W2")
    assert len(calls) == 1
    facts_arg, context_arg, witnesses_arg = calls[0]
    assert facts_arg is None
    assert isinstance(context_arg, dict)
    assert context_arg["lifecycle_phase"] == "waiting"
    assert isinstance(witnesses_arg, dict)
    assert witnesses_arg["current_identity"] == "sase@9fd8a08"


def test_stale_verdict_schema_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_classify(
        facts: object, context: object, witnesses: object
    ) -> dict[str, object]:
        return {"schema_version": 999, "mode": "relaunch"}

    install_fake_rust_extension(monkeypatch, classify_agent_failure=fake_classify)

    with pytest.raises(RuntimeError, match="stale"):
        classify_agent_failure(_context(), _witnesses())


def test_facade_ledger_claim_and_advance(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_claim(key: str, lineage_root: str) -> dict[str, object]:
        return {
            "schema_version": AGENT_AUTO_RESTART_WIRE_SCHEMA_VERSION,
            "key": key,
            "lineage_root": lineage_root,
            "state": "claimed",
            "deferrals": 0,
            "history": [{"state": "claimed", "at": None, "note": "claimed"}],
        }

    def fake_advance(record: dict[str, object], event: str) -> dict[str, object]:
        assert event == "defer"
        updated = dict(record)
        updated["state"] = "deferred"
        updated["deferrals"] = 1
        return updated

    install_fake_rust_extension(
        monkeypatch,
        claim_auto_restart_ledger=fake_claim,
        advance_auto_restart_ledger=fake_advance,
    )

    record = claim_auto_restart_ledger("k", "root")
    assert record.state == "claimed"
    deferred = advance_auto_restart_ledger(record, "defer")
    assert deferred.state == "deferred"
    assert deferred.deferrals == 1


def test_facade_advance_surfaces_value_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_advance(record: dict[str, object], event: str) -> dict[str, object]:
        raise ValueError("illegal auto-restart ledger transition")

    install_fake_rust_extension(monkeypatch, advance_auto_restart_ledger=fake_advance)

    from sase.core.agent_auto_restart_wire import AutoRestartLedgerRecordWire

    with pytest.raises(ValueError, match="illegal auto-restart"):
        advance_auto_restart_ledger(
            AutoRestartLedgerRecordWire(state="claimed"), "settled_ok"
        )


def test_facade_episode_lineage_and_in_flight(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_episode(witnesses: dict[str, object]) -> dict[str, object]:
        return {
            "schema_version": AGENT_AUTO_RESTART_WIRE_SCHEMA_VERSION,
            "id": "sase@9fd8a08",
            "slug": "sase-9fd8a08",
            "culprit_short": "9fd8a08",
            "from_rev": "9c5000f",
            "to_rev": "9fd8a08",
            "label": "sase update 9fd8a08",
        }

    install_fake_rust_extension(
        monkeypatch,
        derive_auto_restart_episode=fake_episode,
        auto_restart_lineage_root=lambda a, b, c: b or c,
        auto_restart_recovery_is_in_flight=lambda state: state == "pending",
        agent_auto_restart_wire_schema_version=lambda: 1,
    )

    episode = derive_auto_restart_episode(_witnesses())
    assert episode.id == "sase@9fd8a08"
    assert (
        auto_restart_lineage_root(
            retry_chain_root_timestamp="chain", artifacts_timestamp="row"
        )
        == "chain"
    )
    assert auto_restart_recovery_is_in_flight("pending") is True
    assert auto_restart_recovery_is_in_flight("declined") is False
    assert auto_restart_wire_schema_version() == 1


def test_done_marker_recovery_round_trip() -> None:
    done = done_marker_from_dict(
        {
            "outcome": "failed",
            "recovery": {
                "state": "pending",
                "episode_id": "sase@9fd8a08",
                "ledger_key": "proj__root",
            },
        }
    )
    assert isinstance(done, DoneMarkerWire)
    assert done.recovery is not None
    assert done.recovery.state == "pending"
    assert done.recovery.episode_id == "sase@9fd8a08"

    legacy = done_marker_from_dict({"outcome": "failed"})
    assert legacy.recovery is None


def test_report_glyph_allowlist_includes_restart() -> None:
    from sase.chops.report import ChopReport

    report = ChopReport(title="restarted")
    report.bullets(["5 agents restarted"], glyph="↻")
    assert report.to_dict()["blocks"][0]["items"][0]["glyph"] == "↻"


def test_in_flight_recovery_row_buckets_active() -> None:
    from sase.agent._running_listing_done import done_info_from_record
    from sase.core.agent_auto_restart_wire import AgentRecoveryWire
    from sase.core.agent_scan_wire_markers import DoneMarkerWire
    from sase.core.agent_scan_wire_records import AgentArtifactRecordWire

    def record_with(recovery: AgentRecoveryWire | None) -> AgentArtifactRecordWire:
        return AgentArtifactRecordWire(
            project_name="home",
            project_dir="/tmp/projects/home",
            project_file="/tmp/projects/home/home.gp",
            workflow_dir_name="ace-run",
            artifact_dir="/tmp/projects/home/ace-run/20261009120000",
            timestamp="20261009120000",
            done=DoneMarkerWire(outcome="failed", recovery=recovery),
            has_done_marker=True,
        )

    from sase.agent.status_buckets import status_bucket_for_values

    pending = done_info_from_record(
        record_with(AgentRecoveryWire(state="pending")),
        clan_contexts={},
    )
    assert pending is not None
    assert pending.status == "RESTARTING"
    assert status_bucket_for_values(pending.status) == "Running"

    failed = done_info_from_record(
        record_with(AgentRecoveryWire(state="declined")),
        clan_contexts={},
    )
    assert failed is not None
    assert failed.status == "FAILED"
    assert status_bucket_for_values(failed.status) == "Failed"
