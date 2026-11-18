"""Shared helpers for the chop-batch subprocess acceptance harness."""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast


HARNESS_ENV = "SASE_CHOP_BATCH_ACCEPTANCE_CONFIG"


def _event_path(config: dict[str, Any], event: str) -> Path:
    return Path(config["events_dir"]) / event


def signal_event(config: dict[str, Any], event: str, payload: str = "") -> None:
    path = _event_path(config, event)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(payload, encoding="utf-8")


def _worker_command(config_path: Path, operation: str) -> list[str]:
    worker = Path(__file__).with_name("chop_batch_process_worker.py")
    return [sys.executable, str(worker), operation, str(config_path)]


def spawn_worker(config_path: Path, operation: str) -> subprocess.Popen[bytes]:
    env = os.environ.copy()
    env[HARNESS_ENV] = str(config_path)
    return subprocess.Popen(
        _worker_command(config_path, operation),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )


def wait_event(
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


def wait_worker(worker: subprocess.Popen[bytes]) -> tuple[int, str, str]:
    stdout, stderr = worker.communicate(timeout=30)
    return worker.returncode or 0, stdout.decode(), stderr.decode()


def kill_worker(worker: subprocess.Popen[bytes], sig: int) -> int:
    worker.send_signal(sig)
    try:
        worker.communicate(timeout=10)
    except subprocess.TimeoutExpired:
        worker.kill()
        worker.communicate(timeout=10)
    return int(worker.returncode or 0)


def read_receipts(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line
    ]


def make_config(
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


def write_config(root: Path, config: dict[str, Any]) -> Path:
    path = root / "configs" / f"{config['run_id']}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(config, sort_keys=True), encoding="utf-8")
    return path


def create_ordinary_batch(
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


def restart(config_path: Path, config: dict[str, Any]) -> dict[str, Any]:
    config["hold_mode"] = None
    config["hold_index"] = None
    config["wait_start"] = False
    config_path.write_text(json.dumps(config, sort_keys=True), encoding="utf-8")
    _event_path(config, "finished").unlink(missing_ok=True)
    worker = spawn_worker(config_path, "recover")
    code, stdout, stderr = wait_worker(worker)
    if code != 0:
        raise AssertionError(f"recovery subprocess failed ({code}): {stderr}{stdout}")
    raw = wait_event(config, "finished")
    return {
        "returncode": code,
        "result": json.loads(raw),
        "stdout": stdout,
        "stderr": stderr,
    }


def assert_receipts(config: dict[str, Any], expected: int) -> list[dict[str, Any]]:
    rows = read_receipts(Path(config["receipt_file"]))
    names = [str(row["agent_name"]) for row in rows]
    if len(rows) != expected or len(set(names)) != expected:
        raise AssertionError(
            f"expected {expected} distinct durable receipts; saw {names!r}"
        )
    return rows


def assert_run_linkage(config: dict[str, Any], expected: int) -> None:
    """Prove every resumed agent carries chop linkage for the original run."""
    from sase.axe.chop_agents import get_chop_agent_records

    records = get_chop_agent_records(
        config["routine"], chop_name=config["job"], run_id=config["run_id"]
    )
    indexes = sorted(
        cast(int, record.proposal_index)
        for record in records
        if record.run_id == config["run_id"]
    )
    if indexes != list(range(expected)):
        raise AssertionError(
            f"expected run linkage for proposal indexes 0..{expected - 1}; "
            f"saw {indexes!r}"
        )


def assert_run_history(config: dict[str, Any], expected: int) -> None:
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


def notification_events(tags: set[str]) -> list[str]:
    from sase.notifications.store import load_notifications

    return [
        tag
        for notification in load_notifications()
        for tag in notification.tags
        if tag in tags
    ]
