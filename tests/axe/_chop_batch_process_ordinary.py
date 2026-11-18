"""Ordinary recovery scenarios for the chop-batch subprocess acceptance harness."""

from __future__ import annotations

from pathlib import Path
from typing import Any
import json
import signal
from tests.axe._chop_batch_process_support import (
    assert_receipts,
    assert_run_history,
    assert_run_linkage,
    make_config,
    create_ordinary_batch,
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


def _archived_notice_episodes(config: dict[str, Any]) -> dict[str, Any]:
    """Return the retired batch's durable notice episodes from run history."""
    import json

    from sase.axe import chop_batch_store
    from sase.axe._chop_batch_store_paths import archived_chop_batch_path

    notices_path = archived_chop_batch_path(
        config["routine"], config["job"], config["run_id"]
    ).with_name(f"{config['run_id']}{chop_batch_store.CHOP_BATCH_NOTICES_SUFFIX}")
    try:
        payload = json.loads(notices_path.read_text(encoding="utf-8"))
    except OSError:
        return {}
    if not isinstance(payload, dict):
        return {}
    episodes = payload.get("episodes")
    return episodes if isinstance(episodes, dict) else {}


def run_ordinary_scenario(root: Path, scenario: str, n: int) -> dict[str, Any]:
    """Run one ordinary recovery acceptance scenario."""
    from sase.axe import chop_batch_store
    from sase.axe.state import read_chop_run_log_tail
    from sase.notifications.store import load_notifications

    if scenario.startswith("ordinary-k-"):
        k = int(scenario.rsplit("-", 1)[1])
        run_id = f"ordinary-k-{k}"
        config = make_config(
            root,
            n=n,
            run_id=run_id,
            hold_mode="after_ack" if 0 < k < n else None,
            hold_index=k - 1 if 0 < k < n else None,
            wait_start=k == 0,
        )
        config_path = write_config(root, config)
        create_ordinary_batch(config)
        worker = spawn_worker(config_path, "ordinary")
        wait_event(config, "ready", worker)
        if k == 0:
            kill_worker(worker, signal.SIGKILL)
        elif k < n:
            wait_event(config, f"ack-{k - 1}", worker)
            kill_worker(worker, signal.SIGKILL)
        else:
            code, _, stderr = wait_worker(worker)
            if code != 0:
                raise AssertionError(f"initial ordinary run failed: {stderr}")

        first_restart = restart(config_path, config)
        rows = assert_receipts(config, n)
        assert_run_linkage(config, n)
        assert_run_history(config, n)
        second_restart = restart(config_path, config)
        if len(read_receipts(Path(config["receipt_file"]))) != n:
            raise AssertionError("second restart launched a duplicate member")
        batch = chop_batch_store.load_chop_batch(
            config["routine"], config["job"], run_id
        )
        return {
            "scenario": scenario,
            "total": n,
            "k": k,
            "remaining": n - k,
            "run_identity": run_id,
            "clan_identity": config["clan"],
            "original_names": config["names"],
            "receipt_names": [row["agent_name"] for row in rows],
            "batch_status": batch["status"],
            "first_restart": first_restart["returncode"],
            "second_restart": second_restart["returncode"],
            "second_restart_new_launches": 0,
        }

    if scenario in {"spawn-before-ack", "reserved-before-spawn"}:
        run_id = scenario
        hold_mode = "after_spawn" if scenario == "spawn-before-ack" else "before_spawn"
        event = "spawned-0" if hold_mode == "after_spawn" else "reserved-0"
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
        wait_event(config, event, worker)
        kill_worker(worker, signal.SIGKILL)
        after_death = len(read_receipts(Path(config["receipt_file"])))
        restart(config_path, config)
        rows = assert_receipts(config, n)
        assert_run_linkage(config, n)
        assert_run_history(config, n)
        restart(config_path, config)
        return {
            "scenario": scenario,
            "total": n,
            "spawned_before_stop": after_death,
            "remaining_after_restart": n - after_death,
            "run_identity": run_id,
            "clan_identity": config["clan"],
            "termination": "SIGKILL after durable fake spawn receipt, before outer acknowledgement",
            "receipt_names": [row["agent_name"] for row in rows],
            "first_restart_result": "resumed original identities",
            "second_restart_new_launches": 0,
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

    if scenario == "sigterm-pause":
        run_id = scenario
        config = make_config(
            root, n=n, run_id=run_id, hold_mode="after_spawn", hold_index=0
        )
        config_path = write_config(root, config)
        create_ordinary_batch(config)
        worker = spawn_worker(config_path, "ordinary")
        wait_event(config, "spawned-0", worker)
        worker.send_signal(signal.SIGTERM)
        signal_event(config, "release-spawned-0")
        code, stdout, stderr = wait_worker(worker)
        if code != 0:
            raise AssertionError(f"SIGTERM recovery failed ({code}): {stderr}{stdout}")
        paused = chop_batch_store.load_chop_batch(
            config["routine"], config["job"], run_id
        )
        if (
            paused["status"] != "paused"
            or len(read_receipts(Path(config["receipt_file"]))) != 1
        ):
            raise AssertionError(
                "SIGTERM did not finish one launch and pause before the next"
            )
        notifications_before = load_notifications()
        restart(config_path, config)
        rows = assert_receipts(config, n)
        assert_run_linkage(config, n)
        assert_run_history(config, n)
        restart(config_path, config)
        notifications_after = load_notifications()
        events = [
            tag
            for notification in notifications_after
            for tag in notification.tags
            if tag in {"interrupted", "resumed"}
        ]
        return {
            "scenario": scenario,
            "total": n,
            "k": 1,
            "remaining": n - 1,
            "first_process_returncode": code,
            "receipt_names": [row["agent_name"] for row in rows],
            "original_names": config["names"],
            "notifications_before_restart": len(notifications_before),
            "notification_events": events,
            "second_restart_new_launches": 0,
        }

    if scenario == "race":
        # A routine tick and a manual run race to recover one interrupted
        # batch. Batch ownership lets exactly one executor dispatch: the loser
        # reports a live owner, launches nothing, and emits no notice.
        run_id = scenario
        base = make_config(
            root, n=n, run_id=run_id, hold_mode="after_ack", hold_index=0
        )
        create_ordinary_batch(base)
        initial = spawn_worker(write_config(root, base), "ordinary")
        wait_event(base, "ack-0", initial)
        kill_worker(initial, signal.SIGKILL)
        config_a = make_config(
            root / "tick",
            n=n,
            run_id=run_id,
            hold_mode="after_spawn",
            hold_index=1,
        )
        config_b = make_config(root / "manual", n=n, run_id=run_id)
        for forked in (config_a, config_b):
            forked["receipt_file"] = base["receipt_file"]
            forked["workspace"] = base["workspace"]
        path_a = write_config(root / "tick", config_a)
        path_b = write_config(root / "manual", config_b)
        worker_a = spawn_worker(path_a, "recover")
        wait_event(config_a, "spawned-1", worker_a)
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
            raise AssertionError("racing run was not held off by the live owner")
        if len(read_receipts(Path(base["receipt_file"]))) != 2:
            raise AssertionError("racing run dispatched while the owner was live")
        signal_event(config_a, "release-spawned-1")
        code_a, _, stderr_a = wait_worker(worker_a)
        if code_a != 0:
            raise AssertionError(f"owning recovery failed: {stderr_a}")
        rows = assert_receipts(base, n)
        assert_run_linkage(base, n)
        assert_run_history(base, n)
        restart(path_a, config_a)
        if len(read_receipts(Path(base["receipt_file"]))) != n:
            raise AssertionError("second restart launched a duplicate member")
        events = notification_events({"interrupted", "resumed"})
        if events.count("interrupted") != 1 or events.count("resumed") != 1:
            raise AssertionError(
                f"race produced duplicate or missing episode notices: {events!r}"
            )
        return {
            "scenario": scenario,
            "total": n,
            "run_identity": run_id,
            "clan_identity": base["clan"],
            "termination": "SIGKILL after first acknowledgement, then racing recoveries",
            "loser_kind": "blocked",
            "receipt_names": [row["agent_name"] for row in rows],
            "original_names": base["names"],
            "notification_events": events,
            "second_restart_new_launches": 0,
        }

    if scenario == "two-episodes":
        # Two separate interruptions produce two episodes, each with exactly
        # one interruption and one resume notice — including delivery of a
        # resume prepared by a recovery that never finished.
        run_id = scenario
        base = make_config(
            root, n=n, run_id=run_id, hold_mode="after_ack", hold_index=0
        )
        create_ordinary_batch(base)
        initial = spawn_worker(write_config(root, base), "ordinary")
        wait_event(base, "ack-0", initial)
        kill_worker(initial, signal.SIGKILL)
        config_a = make_config(
            root / "restart1",
            n=n,
            run_id=run_id,
            hold_mode="after_spawn",
            hold_index=2,
        )
        for forked in (config_a,):
            forked["receipt_file"] = base["receipt_file"]
            forked["workspace"] = base["workspace"]
        worker_a = spawn_worker(write_config(root / "restart1", config_a), "recover")
        wait_event(config_a, "spawned-2", worker_a)
        kill_worker(worker_a, signal.SIGKILL)
        config_b = make_config(root / "restart2", n=n, run_id=run_id)
        config_b["receipt_file"] = base["receipt_file"]
        config_b["workspace"] = base["workspace"]
        path_b = write_config(root / "restart2", config_b)
        restart(path_b, config_b)
        rows = assert_receipts(base, n)
        assert_run_linkage(base, n)
        assert_run_history(base, n)
        restart(path_b, config_b)
        if len(read_receipts(Path(base["receipt_file"]))) != n:
            raise AssertionError("second restart launched a duplicate member")
        events = notification_events({"interrupted", "resumed"})
        if events.count("interrupted") != 2 or events.count("resumed") != 2:
            raise AssertionError(
                f"expected two interruption and two resume notices: {events!r}"
            )
        # The live outbox retires into run history when the batch
        # completes; the archived copy is the durable per-episode record.
        episodes = _archived_notice_episodes(base)
        complete = [
            episode_id
            for episode_id, episode in episodes.items()
            if isinstance(episode, dict)
            and isinstance(episode.get("events"), dict)
            and bool((episode["events"].get("interrupted") or {}).get("delivered"))
            and bool((episode["events"].get("resumed") or {}).get("delivered"))
        ]
        if len(complete) != 2:
            raise AssertionError(
                f"expected two delivered notice episodes, saw {len(complete)}"
            )
        return {
            "scenario": scenario,
            "total": n,
            "run_identity": run_id,
            "clan_identity": base["clan"],
            "termination": "SIGKILL, recovery, SIGKILL during recovery, recovery",
            "receipt_names": [row["agent_name"] for row in rows],
            "original_names": base["names"],
            "notification_events": events,
            "delivered_episodes": len(complete),
            "second_restart_new_launches": 0,
        }

    raise ValueError(f"unknown acceptance scenario {scenario!r}")
