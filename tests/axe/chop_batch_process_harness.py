"""Subprocess acceptance harness for chop-batch interruption and recovery.

The harness replaces only the agent workload with a short-lived child that
writes a durable fake launch receipt. The chop batch store, ordinary replay,
typed admission, restart recovery, notification store, and lumberjack SIGTERM
handler remain production code.

Run the disposable manual demonstration with::

    python -m tests.axe.chop_batch_process_harness demo
"""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import tempfile
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


HARNESS_ENV = "SASE_CHOP_BATCH_ACCEPTANCE_CONFIG"


def _event_path(config: dict[str, Any], event: str) -> Path:
    return Path(config["events_dir"]) / event


def _signal_event(config: dict[str, Any], event: str, payload: str = "") -> None:
    path = _event_path(config, event)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(payload, encoding="utf-8")


def _worker_command(config_path: Path, operation: str) -> list[str]:
    worker = Path(__file__).with_name("chop_batch_process_worker.py")
    return [sys.executable, str(worker), operation, str(config_path)]


def _spawn_worker(config_path: Path, operation: str) -> subprocess.Popen[bytes]:
    env = os.environ.copy()
    env[HARNESS_ENV] = str(config_path)
    return subprocess.Popen(
        _worker_command(config_path, operation),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )


def _wait_event(
    config: dict[str, Any], event: str, worker: subprocess.Popen[bytes] | None = None
) -> str:
    path = _event_path(config, event)
    deadline = time.monotonic() + 30
    while not path.exists():
        if worker is not None and worker.poll() is not None:
            stdout, stderr = worker.communicate()
            raise AssertionError(
                f"worker exited before event {event!r} "
                f"({worker.returncode}): {stderr.decode()}{stdout.decode()}"
            )
        if time.monotonic() >= deadline:
            raise TimeoutError(f"timed out waiting for event {event!r}")
        time.sleep(0.01)  # sase-test-wait: Poll an explicit file handshake token.
    return path.read_text(encoding="utf-8")


def _wait_worker(worker: subprocess.Popen[bytes]) -> tuple[int, str, str]:
    stdout, stderr = worker.communicate(timeout=30)
    return worker.returncode or 0, stdout.decode(), stderr.decode()


def _kill_worker(worker: subprocess.Popen[bytes], sig: int) -> int:
    worker.send_signal(sig)
    try:
        worker.communicate(timeout=10)
    except subprocess.TimeoutExpired:
        worker.kill()
        worker.communicate(timeout=10)
    return int(worker.returncode or 0)


def _read_receipts(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line
    ]


def _config(
    root: Path,
    *,
    n: int,
    run_id: str,
    hold_mode: str | None = None,
    hold_index: int | None = None,
    wait_start: bool = False,
) -> dict[str, Any]:
    names = [f"acceptance-{run_id}-{index}" for index in range(n)]
    return {
        "routine": "disposable",
        "job": "acceptance",
        "run_id": run_id,
        "n": n,
        "names": names,
        "clan": f"clan-{run_id}",
        "generation": f"generation-{run_id}",
        "events_dir": str(root / "events" / run_id),
        "receipt_file": str(root / "receipts" / f"{run_id}.jsonl"),
        "workspace": str(root / "workspace"),
        "hold_mode": hold_mode,
        "hold_index": hold_index,
        "wait_start": wait_start,
    }


def _write_config(root: Path, config: dict[str, Any]) -> Path:
    path = root / "configs" / f"{config['run_id']}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(config, sort_keys=True), encoding="utf-8")
    return path


def _create_ordinary_batch(
    config: dict[str, Any],
    clans: list[str] | None = None,
) -> None:
    from sase.axe.chop_batch_store import create_chop_batch
    from sase.axe.state import ChopRunEntry, start_chop_run
    from sase.core.axe_chop_facade import CHOP_BATCH_SCHEMA_VERSION

    start_chop_run(
        ChopRunEntry(
            run_id=config["run_id"],
            lumberjack_name=config["routine"],
            chop_name=config["job"],
            started_at=datetime.now(UTC).isoformat(),
            finished_at=None,
            duration_ms=0,
            status="running",
        )
    )
    clan_names = clans or [config["clan"]]
    members = [
        {
            "source_index": index,
            "proposal_id": f"proposal-{index}",
            "agent_name": name,
            "prompt": f"%id:{name}\nReview disposable input {index}.",
            "workspace": "git:sase",
            "clan": clan_names[index % len(clan_names)],
            "clan_generation": config["generation"],
        }
        for index, name in enumerate(config["names"])
    ]
    create_chop_batch(
        config["routine"],
        config["job"],
        {
            "schema_version": CHOP_BATCH_SCHEMA_VERSION,
            "batch_id": config["run_id"],
            "run": {
                "routine": config["routine"],
                "job": config["job"],
                "run_id": config["run_id"],
            },
            "clan": config["clan"],
            "clan_generation": config["generation"],
            "members": members,
        },
    )


def _restart(config_path: Path, config: dict[str, Any]) -> dict[str, Any]:
    config["hold_mode"] = None
    config["hold_index"] = None
    config["wait_start"] = False
    config_path.write_text(json.dumps(config, sort_keys=True), encoding="utf-8")
    _event_path(config, "finished").unlink(missing_ok=True)
    worker = _spawn_worker(config_path, "recover")
    code, stdout, stderr = _wait_worker(worker)
    if code != 0:
        raise AssertionError(f"recovery subprocess failed ({code}): {stderr}{stdout}")
    raw = _wait_event(config, "finished")
    return {
        "returncode": code,
        "result": json.loads(raw),
        "stdout": stdout,
        "stderr": stderr,
    }


def _assert_receipts(config: dict[str, Any], expected: int) -> list[dict[str, Any]]:
    rows = _read_receipts(Path(config["receipt_file"]))
    names = [str(row["agent_name"]) for row in rows]
    if len(rows) != expected or len(set(names)) != expected:
        raise AssertionError(
            f"expected {expected} distinct durable receipts; saw {names!r}"
        )
    return rows


def _assert_run_linkage(config: dict[str, Any], expected: int) -> None:
    """Prove every resumed agent carries chop linkage for the original run."""
    from sase.axe.chop_agents import get_chop_agent_records

    records = get_chop_agent_records(
        config["routine"], chop_name=config["job"], run_id=config["run_id"]
    )
    indexes = sorted(
        record.proposal_index for record in records if record.run_id == config["run_id"]
    )
    if indexes != list(range(expected)):
        raise AssertionError(
            f"expected run linkage for proposal indexes 0..{expected - 1}; "
            f"saw {indexes!r}"
        )


def _assert_run_history(config: dict[str, Any], expected: int) -> None:
    """Prove the original run's history lists every launch exactly once."""
    from sase.axe.state import read_chop_run

    entry = read_chop_run(config["routine"], config["job"], config["run_id"])
    launches = list(entry.launches) if entry is not None else []
    keys = [
        (launch.get("index"), str(launch.get("agent_name")), launch.get("pid"))
        for launch in launches
        if isinstance(launch, dict)
    ]
    if len(keys) != expected or len(set(keys)) != expected:
        raise AssertionError(
            f"expected {expected} distinct run-history launches; saw {keys!r}"
        )


def _archived_notice_episodes(config: dict[str, Any]) -> dict[str, Any]:
    """Return the retired batch's durable notice episodes from run history."""
    import json

    from sase.axe import chop_batch_store

    notices_path = chop_batch_store._archived_chop_batch_path(
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


def _member_names(config: dict[str, Any]) -> list[str]:
    """Return batch member identities in proposal order (planner-namespaced)."""
    from sase.axe import chop_batch_store

    manifest = chop_batch_store.load_chop_batch(
        config["routine"], config["job"], config["run_id"]
    )
    members = [
        member for member in (manifest.get("members") or []) if isinstance(member, dict)
    ]
    members.sort(key=lambda member: member.get("source_index"))
    return [str(member.get("agent_name")) for member in members]


def _notification_events(tags: set[str]) -> list[str]:
    from sase.notifications.store import load_notifications

    return [
        tag
        for notification in load_notifications()
        for tag in notification.tags
        if tag in tags
    ]


def run_scenario(root: Path, scenario: str) -> dict[str, Any]:
    """Run one disposable subprocess acceptance scenario and return evidence."""
    root = root.resolve()
    root.mkdir(parents=True, exist_ok=True)
    os.environ["SASE_HOME"] = str(root / "state")
    n = 4
    from sase.axe import chop_batch_store
    from sase.axe.chop_batch_recovery import cancel_chop_batches_for_clan
    from sase.axe.state import read_chop_run_log_tail
    from sase.notifications.store import load_notifications

    if scenario.startswith("ordinary-k-"):
        k = int(scenario.rsplit("-", 1)[1])
        run_id = f"ordinary-k-{k}"
        config = _config(
            root,
            n=n,
            run_id=run_id,
            hold_mode="after_ack" if 0 < k < n else None,
            hold_index=k - 1 if 0 < k < n else None,
            wait_start=k == 0,
        )
        config_path = _write_config(root, config)
        _create_ordinary_batch(config)
        worker = _spawn_worker(config_path, "ordinary")
        _wait_event(config, "ready", worker)
        if k == 0:
            _kill_worker(worker, signal.SIGKILL)
        elif k < n:
            _wait_event(config, f"ack-{k - 1}", worker)
            _kill_worker(worker, signal.SIGKILL)
        else:
            code, _, stderr = _wait_worker(worker)
            if code != 0:
                raise AssertionError(f"initial ordinary run failed: {stderr}")

        first_restart = _restart(config_path, config)
        rows = _assert_receipts(config, n)
        _assert_run_linkage(config, n)
        _assert_run_history(config, n)
        second_restart = _restart(config_path, config)
        if len(_read_receipts(Path(config["receipt_file"]))) != n:
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
        config = _config(
            root,
            n=n,
            run_id=run_id,
            hold_mode=hold_mode,
            hold_index=0,
        )
        config_path = _write_config(root, config)
        _create_ordinary_batch(config)
        worker = _spawn_worker(config_path, "ordinary")
        _wait_event(config, event, worker)
        _kill_worker(worker, signal.SIGKILL)
        after_death = len(_read_receipts(Path(config["receipt_file"])))
        _restart(config_path, config)
        rows = _assert_receipts(config, n)
        _assert_run_linkage(config, n)
        _assert_run_history(config, n)
        _restart(config_path, config)
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
        config = _config(
            root, n=n, run_id=run_id, hold_mode="after_spawn", hold_index=0
        )
        config_path = _write_config(root, config)
        _create_ordinary_batch(config)
        worker = _spawn_worker(config_path, "ordinary")
        _wait_event(config, "spawned-0", worker)
        worker.send_signal(signal.SIGTERM)
        _signal_event(config, "release-spawned-0")
        code, stdout, stderr = _wait_worker(worker)
        if code != 0:
            raise AssertionError(f"SIGTERM recovery failed ({code}): {stderr}{stdout}")
        paused = chop_batch_store.load_chop_batch(
            config["routine"], config["job"], run_id
        )
        if (
            paused["status"] != "paused"
            or len(_read_receipts(Path(config["receipt_file"]))) != 1
        ):
            raise AssertionError(
                "SIGTERM did not finish one launch and pause before the next"
            )
        notifications_before = load_notifications()
        _restart(config_path, config)
        rows = _assert_receipts(config, n)
        _assert_run_linkage(config, n)
        _assert_run_history(config, n)
        _restart(config_path, config)
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

    if scenario == "typed-sigterm-pause":
        run_id = scenario
        config = _config(
            root, n=n, run_id=run_id, hold_mode="after_spawn", hold_index=0
        )
        config_path = _write_config(root, config)
        worker = _spawn_worker(config_path, "typed-start")
        _wait_event(config, "ready", worker)
        _wait_event(config, "spawned-0", worker)
        worker.send_signal(signal.SIGTERM)
        _signal_event(config, "release-spawned-0")
        code, stdout, stderr = _wait_worker(worker)
        if code != 0:
            raise AssertionError(f"typed SIGTERM run failed ({code}): {stderr}{stdout}")
        paused = chop_batch_store.load_chop_batch(
            config["routine"], config["job"], run_id
        )
        if paused["status"] != "paused":
            raise AssertionError(
                f"typed SIGTERM did not pause batch: {paused['status']}"
            )
        launched_before_restart = len(_read_receipts(Path(config["receipt_file"])))
        if launched_before_restart != 1:
            raise AssertionError(
                "typed SIGTERM did not finish exactly the active launch before pausing"
            )
        first_restart = _restart(config_path, config)
        rows = _assert_receipts(config, n)
        _assert_run_linkage(config, n)
        _assert_run_history(config, n)
        member_names = _member_names(config)
        if [row["agent_name"] for row in rows] != member_names:
            raise AssertionError(
                "typed receipts do not match batch member identities: "
                f"{[row['agent_name'] for row in rows]!r} != {member_names!r}"
            )
        second_restart = _restart(config_path, config)
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

    if scenario in {"cancel-paused", "cancel-active"}:
        run_id = scenario
        hold_mode = "after_ack" if scenario == "cancel-paused" else "after_spawn"
        config = _config(
            root,
            n=n,
            run_id=run_id,
            hold_mode=hold_mode,
            hold_index=0,
        )
        config_path = _write_config(root, config)
        _create_ordinary_batch(config)
        worker = _spawn_worker(config_path, "ordinary")
        event = "ack-0" if scenario == "cancel-paused" else "spawned-0"
        _wait_event(config, event, worker)
        if scenario == "cancel-paused":
            worker.send_signal(signal.SIGTERM)
            _signal_event(config, f"release-{event}")
            code, _, stderr = _wait_worker(worker)
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
            _signal_event(config, f"release-{event}")
            code, stdout, stderr = _wait_worker(worker)
            if code != 0:
                raise AssertionError(
                    f"active cancellation recovery failed: {stderr}{stdout}"
                )
        receipt_file = Path(config["receipt_file"])
        before_cleanup = len(_read_receipts(receipt_file))
        _assert_run_history(config, 1)
        receipt_file.unlink(missing_ok=True)
        _restart(config_path, config)
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
            "launches_after_cleanup_restart": len(_read_receipts(receipt_file)),
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

    if scenario == "race":
        # A routine tick and a manual run race to recover one interrupted
        # batch. Batch ownership lets exactly one executor dispatch: the loser
        # reports a live owner, launches nothing, and emits no notice.
        run_id = scenario
        base = _config(root, n=n, run_id=run_id, hold_mode="after_ack", hold_index=0)
        _create_ordinary_batch(base)
        initial = _spawn_worker(_write_config(root, base), "ordinary")
        _wait_event(base, "ack-0", initial)
        _kill_worker(initial, signal.SIGKILL)
        config_a = _config(
            root / "tick",
            n=n,
            run_id=run_id,
            hold_mode="after_spawn",
            hold_index=1,
        )
        config_b = _config(root / "manual", n=n, run_id=run_id)
        for forked in (config_a, config_b):
            forked["receipt_file"] = base["receipt_file"]
            forked["workspace"] = base["workspace"]
        path_a = _write_config(root / "tick", config_a)
        path_b = _write_config(root / "manual", config_b)
        worker_a = _spawn_worker(path_a, "recover")
        _wait_event(config_a, "spawned-1", worker_a)
        worker_b = _spawn_worker(path_b, "recover")
        raw_b = _wait_event(config_b, "finished")
        code_b, _, stderr_b = _wait_worker(worker_b)
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
        if len(_read_receipts(Path(base["receipt_file"]))) != 2:
            raise AssertionError("racing run dispatched while the owner was live")
        _signal_event(config_a, "release-spawned-1")
        code_a, _, stderr_a = _wait_worker(worker_a)
        if code_a != 0:
            raise AssertionError(f"owning recovery failed: {stderr_a}")
        rows = _assert_receipts(base, n)
        _assert_run_linkage(base, n)
        _assert_run_history(base, n)
        _restart(path_a, config_a)
        if len(_read_receipts(Path(base["receipt_file"]))) != n:
            raise AssertionError("second restart launched a duplicate member")
        events = _notification_events({"interrupted", "resumed"})
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

    if scenario == "cancel-during-recovery":
        # A clan kill lands while recovery dispatch is in flight. The
        # crossing member settles as launched evidence, later members never
        # start, and a restart launches nothing.
        run_id = scenario
        config = _config(
            root, n=n, run_id=run_id, hold_mode="after_spawn", hold_index=1
        )
        config_path = _write_config(root, config)
        _create_ordinary_batch(config)
        worker = _spawn_worker(config_path, "recover")
        _wait_event(config, "spawned-1", worker)
        cancelled = cancel_chop_batches_for_clan(
            config["clan"],
            generation=config["generation"],
            reason="disposable acceptance recovery-active clan kill",
            routine=config["routine"],
            job=config["job"],
        )
        if len(cancelled) != 1:
            raise AssertionError(f"expected one cancelled batch, got {cancelled!r}")
        _signal_event(config, "release-spawned-1")
        code, stdout, stderr = _wait_worker(worker)
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
        rows = _read_receipts(Path(config["receipt_file"]))
        if len(rows) != 2:
            raise AssertionError(
                "crossing member did not settle exactly once: "
                f"{[row['agent_name'] for row in rows]!r}"
            )
        _assert_run_history(config, 2)
        _restart(config_path, config)
        if len(_read_receipts(Path(config["receipt_file"]))) != 2:
            raise AssertionError("cancelled batch revived a member on restart")
        events = _notification_events({"cancelled"})
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
        config = _config(root, n=n, run_id=run_id)
        config_path = _write_config(root, config)
        _create_ordinary_batch(config, clans=clans)
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
        _restart(config_path, config)
        if _read_receipts(Path(config["receipt_file"])):
            raise AssertionError("cancelled multi-clan batch launched on restart")
        _assert_run_history(config, 0)
        events = _notification_events({"cancelled"})
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

    if scenario == "two-episodes":
        # Two separate interruptions produce two episodes, each with exactly
        # one interruption and one resume notice — including delivery of a
        # resume prepared by a recovery that never finished.
        run_id = scenario
        base = _config(root, n=n, run_id=run_id, hold_mode="after_ack", hold_index=0)
        _create_ordinary_batch(base)
        initial = _spawn_worker(_write_config(root, base), "ordinary")
        _wait_event(base, "ack-0", initial)
        _kill_worker(initial, signal.SIGKILL)
        config_a = _config(
            root / "restart1",
            n=n,
            run_id=run_id,
            hold_mode="after_spawn",
            hold_index=2,
        )
        for forked in (config_a,):
            forked["receipt_file"] = base["receipt_file"]
            forked["workspace"] = base["workspace"]
        worker_a = _spawn_worker(_write_config(root / "restart1", config_a), "recover")
        _wait_event(config_a, "spawned-2", worker_a)
        _kill_worker(worker_a, signal.SIGKILL)
        config_b = _config(root / "restart2", n=n, run_id=run_id)
        config_b["receipt_file"] = base["receipt_file"]
        config_b["workspace"] = base["workspace"]
        path_b = _write_config(root / "restart2", config_b)
        _restart(path_b, config_b)
        rows = _assert_receipts(base, n)
        _assert_run_linkage(base, n)
        _assert_run_history(base, n)
        _restart(path_b, config_b)
        if len(_read_receipts(Path(base["receipt_file"]))) != n:
            raise AssertionError("second restart launched a duplicate member")
        events = _notification_events({"interrupted", "resumed"})
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

    if scenario == "typed-kill":
        # SIGKILL between spawn and acknowledgement on the typed path. The
        # linkage-proven dispatch folds to launched instead of skipping, so
        # no member is lost or duplicated.
        run_id = scenario
        config = _config(
            root, n=n, run_id=run_id, hold_mode="after_spawn", hold_index=0
        )
        config_path = _write_config(root, config)
        worker = _spawn_worker(config_path, "typed-start")
        _wait_event(config, "ready", worker)
        _wait_event(config, "spawned-0", worker)
        _kill_worker(worker, signal.SIGKILL)
        first_restart = _restart(config_path, config)
        rows = _assert_receipts(config, n)
        _assert_run_linkage(config, n)
        _assert_run_history(config, n)
        member_names = _member_names(config)
        if [row["agent_name"] for row in rows] != member_names:
            raise AssertionError(
                "typed receipts do not match batch member identities: "
                f"{[row['agent_name'] for row in rows]!r} != {member_names!r}"
            )
        second_restart = _restart(config_path, config)
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
        config = _config(
            root, n=n, run_id=run_id, hold_mode="after_spawn", hold_index=0
        )
        config_path = _write_config(root, config)
        worker = _spawn_worker(config_path, "typed-start")
        _wait_event(config, "ready", worker)
        _wait_event(config, "spawned-0", worker)
        worker.send_signal(signal.SIGTERM)
        _signal_event(config, "release-spawned-0")
        code, stdout, stderr = _wait_worker(worker)
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
        _restart(config_path, config)
        batch = chop_batch_store.load_chop_batch(
            config["routine"], config["job"], run_id
        )
        if batch["status"] != "cancelled":
            raise AssertionError("typed cancelled batch did not retain cancellation")
        if len(_read_receipts(Path(config["receipt_file"]))) != 1:
            raise AssertionError("typed cancel lost the settled launch receipt")
        _assert_run_history(config, 1)
        events = _notification_events({"cancelled"})
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
        config_a = _config(
            root / "first",
            n=n,
            run_id=run_id,
            hold_mode="after_spawn",
            hold_index=0,
        )
        config_b = _config(root / "manual", n=n, run_id=run_id)
        for forked in (config_a, config_b):
            forked["receipt_file"] = str(root / "receipts" / f"{run_id}.jsonl")
            forked["workspace"] = str(root / "workspace")
        path_a = _write_config(root / "first", config_a)
        path_b = _write_config(root / "manual", config_b)
        worker_a = _spawn_worker(path_a, "typed-start")
        _wait_event(config_a, "ready", worker_a)
        _wait_event(config_a, "spawned-0", worker_a)
        worker_b = _spawn_worker(path_b, "recover")
        raw_b = _wait_event(config_b, "finished")
        code_b, _, stderr_b = _wait_worker(worker_b)
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
        if len(_read_receipts(Path(config_a["receipt_file"]))) != 1:
            raise AssertionError(
                "racing run dispatched while the first run owned the batch"
            )
        _signal_event(config_a, "release-spawned-0")
        code_a, _, stderr_a = _wait_worker(worker_a)
        if code_a != 0:
            raise AssertionError(f"typed first run failed: {stderr_a}")
        rows = _assert_receipts(config_a, n)
        _assert_run_linkage(config_a, n)
        _assert_run_history(config_a, n)
        member_names = _member_names(config_a)
        if [row["agent_name"] for row in rows] != member_names:
            raise AssertionError(
                "typed receipts do not match batch member identities: "
                f"{[row['agent_name'] for row in rows]!r} != {member_names!r}"
            )
        _restart(path_a, config_a)
        if len(_read_receipts(Path(config_a["receipt_file"]))) != n:
            raise AssertionError("restart after first run duplicated a member")
        events = _notification_events({"interrupted", "resumed"})
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


def _run_demo(root: Path) -> dict[str, Any]:
    evidence = {
        "manual_stop_resume": run_scenario(root / "stop-resume", "spawn-before-ack"),
        "manual_clan_kill": run_scenario(root / "clan-kill", "cancel-paused"),
    }
    return evidence


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if args and args[0] == "demo":
        with tempfile.TemporaryDirectory(prefix="sase-chop-batch-demo-") as temp:
            print(json.dumps(_run_demo(Path(temp)), indent=2, sort_keys=True))
        return 0
    raise SystemExit("usage: python -m tests.axe.chop_batch_process_harness demo")


if __name__ == "__main__":
    raise SystemExit(main())
