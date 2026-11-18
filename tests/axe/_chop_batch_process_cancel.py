"""Cancellation scenarios for the chop-batch subprocess acceptance harness."""

from __future__ import annotations

from pathlib import Path
from typing import Any
import signal
from tests.axe._chop_batch_process_support import (
    assert_run_history,
    make_config,
    create_ordinary_batch,
    notification_events,
    read_receipts,
    restart,
    signal_event,
    spawn_worker,
    wait_event,
    wait_worker,
    write_config,
)


def run_cancellation_scenario(root: Path, scenario: str, n: int) -> dict[str, Any]:
    """Run one cancellation acceptance scenario."""
    from sase.axe import chop_batch_store
    from sase.axe.chop_batch_recovery import cancel_chop_batches_for_clan
    from sase.axe.state import read_chop_run_log_tail
    from sase.notifications.store import load_notifications

    if scenario in {"cancel-paused", "cancel-active"}:
        run_id = scenario
        hold_mode = "after_ack" if scenario == "cancel-paused" else "after_spawn"
        config = make_config(
            root,
            n=n,
            run_id=run_id,
            hold_mode=hold_mode,
            hold_index=0,
        )
        config_path = write_config(root, config)
        create_ordinary_batch(config)
        worker = spawn_worker(config_path, "ordinary")
        event = "ack-0" if scenario == "cancel-paused" else "spawned-0"
        wait_event(config, event, worker)
        if scenario == "cancel-paused":
            worker.send_signal(signal.SIGTERM)
            signal_event(config, f"release-{event}")
            code, _, stderr = wait_worker(worker)
            if code != 0:
                raise AssertionError(f"pause before cancellation failed: {stderr}")
        cancelled = cancel_chop_batches_for_clan(
            config["clan"],
            generation=config["generation"],
            reason="disposable acceptance clan kill",
            routine=config["routine"],
            job=config["job"],
        )
        if len(cancelled) != 1:
            raise AssertionError(f"expected one cancelled batch, got {cancelled!r}")
        if scenario == "cancel-active":
            signal_event(config, f"release-{event}")
            code, stdout, stderr = wait_worker(worker)
            if code != 0:
                raise AssertionError(
                    f"active cancellation recovery failed: {stderr}{stdout}"
                )
        receipt_file = Path(config["receipt_file"])
        before_cleanup = len(read_receipts(receipt_file))
        assert_run_history(config, 1)
        receipt_file.unlink(missing_ok=True)
        restart(config_path, config)
        batch = chop_batch_store.load_chop_batch(
            config["routine"], config["job"], run_id
        )
        if batch["status"] != "cancelled" or receipt_file.exists():
            raise AssertionError(
                "cancelled intent revived after disposable artifact cleanup"
            )
        return {
            "scenario": scenario,
            "run_identity": run_id,
            "clan_identity": config["clan"],
            "termination": "SIGTERM pause followed by explicit clan-generation kill",
            "cancelled_batches": len(cancelled),
            "launches_before_cleanup": before_cleanup,
            "launches_after_cleanup_restart": len(read_receipts(receipt_file)),
            "retained_status": batch["status"],
            "notifications": [
                {
                    "dedup_key": notification.dedup_key,
                    "tags": list(notification.tags),
                }
                for notification in load_notifications()
                if notification.sender == "chop-batch-recovery"
            ],
            "log_tail": read_chop_run_log_tail(
                config["routine"], config["job"], run_id, lines=20
            ),
        }

    if scenario == "cancel-during-recovery":
        # A clan kill lands while recovery dispatch is in flight. The
        # crossing member settles as launched evidence, later members never
        # start, and a restart launches nothing.
        run_id = scenario
        config = make_config(
            root, n=n, run_id=run_id, hold_mode="after_spawn", hold_index=1
        )
        config_path = write_config(root, config)
        create_ordinary_batch(config)
        worker = spawn_worker(config_path, "recover")
        wait_event(config, "spawned-1", worker)
        cancelled = cancel_chop_batches_for_clan(
            config["clan"],
            generation=config["generation"],
            reason="disposable acceptance recovery-active clan kill",
            routine=config["routine"],
            job=config["job"],
        )
        if len(cancelled) != 1:
            raise AssertionError(f"expected one cancelled batch, got {cancelled!r}")
        signal_event(config, "release-spawned-1")
        code, stdout, stderr = wait_worker(worker)
        if code != 0:
            raise AssertionError(
                f"recovery-active cancellation failed: {stderr}{stdout}"
            )
        batch = chop_batch_store.load_chop_batch(
            config["routine"], config["job"], run_id
        )
        if batch["status"] != "cancelled":
            raise AssertionError(
                f"recovery-active kill did not cancel the batch: {batch['status']}"
            )
        rows = read_receipts(Path(config["receipt_file"]))
        if len(rows) != 2:
            raise AssertionError(
                "crossing member did not settle exactly once: "
                f"{[row['agent_name'] for row in rows]!r}"
            )
        assert_run_history(config, 2)
        restart(config_path, config)
        if len(read_receipts(Path(config["receipt_file"]))) != 2:
            raise AssertionError("cancelled batch revived a member on restart")
        events = notification_events({"cancelled"})
        if "cancelled" not in events:
            raise AssertionError("recovery-active kill emitted no cancelled notice")
        return {
            "scenario": scenario,
            "run_identity": run_id,
            "clan_identity": config["clan"],
            "termination": "clan kill while recovery dispatch was in flight",
            "retained_status": batch["status"],
            "settled_launches": len(rows),
            "notification_events": events,
            "second_restart_new_launches": 0,
        }

    if scenario == "multi-clan":
        # One batch spans two clans. Killing either clan cancels the whole
        # batch; an unrelated clan and a stale generation leave it alone.
        run_id = scenario
        clans = [f"clan-{run_id}-a", f"clan-{run_id}-b"]
        config = make_config(root, n=n, run_id=run_id)
        config_path = write_config(root, config)
        create_ordinary_batch(config, clans=clans)
        from sase.axe._chop_batch_recovery_shared import batch_clans

        manifest = chop_batch_store.load_chop_batch(
            config["routine"], config["job"], run_id
        )
        if not frozenset(clans) <= batch_clans(manifest):
            raise AssertionError(
                f"batch does not span both clans: {batch_clans(manifest)!r}"
            )
        kill_kwargs: dict[str, Any] = {
            "reason": "disposable acceptance multi-clan kill",
            "routine": config["routine"],
            "job": config["job"],
        }
        if cancel_chop_batches_for_clan(
            "clan-unrelated", generation=config["generation"], **kill_kwargs
        ):
            raise AssertionError("unrelated clan kill cancelled the batch")
        if cancel_chop_batches_for_clan(
            clans[1], generation="generation-mismatch", **kill_kwargs
        ):
            raise AssertionError("stale generation kill cancelled the batch")
        cancelled = cancel_chop_batches_for_clan(
            clans[1], generation=config["generation"], **kill_kwargs
        )
        if len(cancelled) != 1:
            raise AssertionError(f"expected one cancelled batch, got {cancelled!r}")
        batch = chop_batch_store.load_chop_batch(
            config["routine"], config["job"], run_id
        )
        if batch["status"] != "cancelled":
            raise AssertionError(
                f"multi-clan kill did not cancel the batch: {batch['status']}"
            )
        restart(config_path, config)
        if read_receipts(Path(config["receipt_file"])):
            raise AssertionError("cancelled multi-clan batch launched on restart")
        assert_run_history(config, 0)
        events = notification_events({"cancelled"})
        if "cancelled" not in events:
            raise AssertionError("multi-clan kill emitted no cancelled notice")
        return {
            "scenario": scenario,
            "run_identity": run_id,
            "clan_identities": clans,
            "termination": "clan kill of the batch's second clan",
            "cancelled_batches": len(cancelled),
            "retained_status": batch["status"],
            "launches_after_restart": 0,
            "notification_events": events,
        }

    raise ValueError(f"unknown acceptance scenario {scenario!r}")
