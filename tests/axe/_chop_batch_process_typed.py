"""Typed admission scenarios for the chop-batch subprocess acceptance harness."""

from __future__ import annotations

from pathlib import Path
from typing import Any, cast
import json
import signal
from tests.axe._chop_batch_process_support import (
    assert_receipts,
    assert_run_history,
    assert_run_linkage,
    make_config,
    kill_worker,
    notification_events,
    read_receipts,
    restart,
    signal_event,
    spawn_worker,
    wait_event,
    wait_worker,
    write_config,
)


def _member_names(config: dict[str, Any]) -> list[str]:
    """Return batch member identities in proposal order (planner-namespaced)."""
    from sase.axe import chop_batch_store

    manifest = chop_batch_store.load_chop_batch(
        config["routine"], config["job"], config["run_id"]
    )
    members = [
        member for member in (manifest.get("members") or []) if isinstance(member, dict)
    ]
    members.sort(key=lambda member: cast(int, member.get("source_index")))
    return [str(member.get("agent_name")) for member in members]


def run_typed_scenario(root: Path, scenario: str, n: int) -> dict[str, Any]:
    """Run one typed admission acceptance scenario."""
    from sase.axe import chop_batch_store
    from sase.axe.chop_batch_recovery import cancel_chop_batches_for_clan

    if scenario == "typed-sigterm-pause":
        run_id = scenario
        config = make_config(
            root, n=n, run_id=run_id, hold_mode="after_spawn", hold_index=0
        )
        config_path = write_config(root, config)
        worker = spawn_worker(config_path, "typed-start")
        wait_event(config, "ready", worker)
        wait_event(config, "spawned-0", worker)
        worker.send_signal(signal.SIGTERM)
        signal_event(config, "release-spawned-0")
        code, stdout, stderr = wait_worker(worker)
        if code != 0:
            raise AssertionError(f"typed SIGTERM run failed ({code}): {stderr}{stdout}")
        paused = chop_batch_store.load_chop_batch(
            config["routine"], config["job"], run_id
        )
        if paused["status"] != "paused":
            raise AssertionError(
                f"typed SIGTERM did not pause batch: {paused['status']}"
            )
        launched_before_restart = len(read_receipts(Path(config["receipt_file"])))
        if launched_before_restart != 1:
            raise AssertionError(
                "typed SIGTERM did not finish exactly the active launch before pausing"
            )
        first_restart = restart(config_path, config)
        rows = assert_receipts(config, n)
        assert_run_linkage(config, n)
        assert_run_history(config, n)
        member_names = _member_names(config)
        if [row["agent_name"] for row in rows] != member_names:
            raise AssertionError(
                "typed receipts do not match batch member identities: "
                f"{[row['agent_name'] for row in rows]!r} != {member_names!r}"
            )
        second_restart = restart(config_path, config)
        return {
            "scenario": scenario,
            "total": n,
            "k": launched_before_restart,
            "remaining": n - launched_before_restart,
            "original_names": member_names,
            "receipt_names": [row["agent_name"] for row in rows],
            "first_restart": first_restart["returncode"],
            "second_restart": second_restart["returncode"],
            "second_restart_new_launches": 0,
            "batch_status": chop_batch_store.load_chop_batch(
                config["routine"], config["job"], run_id
            )["status"],
        }

    if scenario == "typed-kill":
        # SIGKILL between spawn and acknowledgement on the typed path. The
        # linkage-proven dispatch folds to launched instead of skipping, so
        # no member is lost or duplicated.
        run_id = scenario
        config = make_config(
            root, n=n, run_id=run_id, hold_mode="after_spawn", hold_index=0
        )
        config_path = write_config(root, config)
        worker = spawn_worker(config_path, "typed-start")
        wait_event(config, "ready", worker)
        wait_event(config, "spawned-0", worker)
        kill_worker(worker, signal.SIGKILL)
        first_restart = restart(config_path, config)
        rows = assert_receipts(config, n)
        assert_run_linkage(config, n)
        assert_run_history(config, n)
        member_names = _member_names(config)
        if [row["agent_name"] for row in rows] != member_names:
            raise AssertionError(
                "typed receipts do not match batch member identities: "
                f"{[row['agent_name'] for row in rows]!r} != {member_names!r}"
            )
        second_restart = restart(config_path, config)
        batch = chop_batch_store.load_chop_batch(
            config["routine"], config["job"], run_id
        )
        return {
            "scenario": scenario,
            "total": n,
            "k": 1,
            "remaining": n - 1,
            "original_names": member_names,
            "receipt_names": [row["agent_name"] for row in rows],
            "batch_status": batch["status"],
            "first_restart": first_restart["returncode"],
            "second_restart": second_restart["returncode"],
            "second_restart_new_launches": 0,
        }

    if scenario == "typed-cancel-paused":
        # Pause a typed first run, then kill its clan. The batch stays
        # cancelled and the one settled launch stays in run history.
        run_id = scenario
        config = make_config(
            root, n=n, run_id=run_id, hold_mode="after_spawn", hold_index=0
        )
        config_path = write_config(root, config)
        worker = spawn_worker(config_path, "typed-start")
        wait_event(config, "ready", worker)
        wait_event(config, "spawned-0", worker)
        worker.send_signal(signal.SIGTERM)
        signal_event(config, "release-spawned-0")
        code, stdout, stderr = wait_worker(worker)
        if code != 0:
            raise AssertionError(f"typed SIGTERM run failed ({code}): {stderr}{stdout}")
        paused = chop_batch_store.load_chop_batch(
            config["routine"], config["job"], run_id
        )
        if paused["status"] != "paused":
            raise AssertionError(
                f"typed SIGTERM did not pause batch: {paused['status']}"
            )
        cancelled = cancel_chop_batches_for_clan(
            config["clan"],
            generation=config["generation"],
            reason="disposable acceptance typed clan kill",
            routine=config["routine"],
            job=config["job"],
        )
        if len(cancelled) != 1:
            raise AssertionError(f"expected one cancelled batch, got {cancelled!r}")
        restart(config_path, config)
        batch = chop_batch_store.load_chop_batch(
            config["routine"], config["job"], run_id
        )
        if batch["status"] != "cancelled":
            raise AssertionError("typed cancelled batch did not retain cancellation")
        if len(read_receipts(Path(config["receipt_file"]))) != 1:
            raise AssertionError("typed cancel lost the settled launch receipt")
        assert_run_history(config, 1)
        events = notification_events({"cancelled"})
        if "cancelled" not in events:
            raise AssertionError("typed clan kill emitted no cancelled notice")
        return {
            "scenario": scenario,
            "run_identity": run_id,
            "clan_identity": config["clan"],
            "termination": "SIGTERM pause followed by explicit clan-generation kill",
            "cancelled_batches": len(cancelled),
            "retained_status": batch["status"],
            "settled_launches": 1,
            "notification_events": events,
        }

    if scenario == "typed-race":
        # A manual recovery races an in-flight typed first run. First-run
        # ownership holds the batch, so the manual run backs off silently and
        # the first run completes all members exactly once.
        run_id = scenario
        config_a = make_config(
            root / "first",
            n=n,
            run_id=run_id,
            hold_mode="after_spawn",
            hold_index=0,
        )
        config_b = make_config(root / "manual", n=n, run_id=run_id)
        for forked in (config_a, config_b):
            forked["receipt_file"] = str(root / "receipts" / f"{run_id}.jsonl")
            forked["workspace"] = str(root / "workspace")
        path_a = write_config(root / "first", config_a)
        path_b = write_config(root / "manual", config_b)
        worker_a = spawn_worker(path_a, "typed-start")
        wait_event(config_a, "ready", worker_a)
        wait_event(config_a, "spawned-0", worker_a)
        worker_b = spawn_worker(path_b, "recover")
        raw_b = wait_event(config_b, "finished")
        code_b, _, stderr_b = wait_worker(worker_b)
        if code_b != 0:
            raise AssertionError(f"racing manual run crashed: {stderr_b}")
        blocked = [
            item
            for item in json.loads(raw_b)
            if item.get("kind") == "blocked"
            and "live owner" in str(item.get("reason") or "")
        ]
        if not blocked:
            raise AssertionError(
                "racing run was not held off by the live first-run owner"
            )
        if len(read_receipts(Path(config_a["receipt_file"]))) != 1:
            raise AssertionError(
                "racing run dispatched while the first run owned the batch"
            )
        signal_event(config_a, "release-spawned-0")
        code_a, _, stderr_a = wait_worker(worker_a)
        if code_a != 0:
            raise AssertionError(f"typed first run failed: {stderr_a}")
        rows = assert_receipts(config_a, n)
        assert_run_linkage(config_a, n)
        assert_run_history(config_a, n)
        member_names = _member_names(config_a)
        if [row["agent_name"] for row in rows] != member_names:
            raise AssertionError(
                "typed receipts do not match batch member identities: "
                f"{[row['agent_name'] for row in rows]!r} != {member_names!r}"
            )
        restart(path_a, config_a)
        if len(read_receipts(Path(config_a["receipt_file"]))) != n:
            raise AssertionError("restart after first run duplicated a member")
        events = notification_events({"interrupted", "resumed"})
        if events:
            raise AssertionError(
                f"uninterrupted first run emitted recovery notices: {events!r}"
            )
        return {
            "scenario": scenario,
            "total": n,
            "run_identity": run_id,
            "clan_identity": config_a["clan"],
            "termination": "manual recovery racing an in-flight typed first run",
            "loser_kind": "blocked",
            "receipt_names": [row["agent_name"] for row in rows],
            "original_names": member_names,
            "notification_events": events,
            "second_restart_new_launches": 0,
        }

    raise ValueError(f"unknown acceptance scenario {scenario!r}")
