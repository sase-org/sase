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


def _create_ordinary_batch(config: dict[str, Any]) -> None:
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
    members = [
        {
            "source_index": index,
            "proposal_id": f"proposal-{index}",
            "agent_name": name,
            "prompt": f"%id:{name}\nReview disposable input {index}.",
            "workspace": "git:sase",
            "clan": config["clan"],
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
        second_restart = _restart(config_path, config)
        return {
            "scenario": scenario,
            "total": n,
            "k": launched_before_restart,
            "remaining": n - launched_before_restart,
            "original_names": config["names"],
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
