"""Child process for the chop-batch acceptance harness."""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any


HARNESS_ENV = "SASE_CHOP_BATCH_ACCEPTANCE_CONFIG"
REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def _read_config() -> dict[str, Any]:
    path = Path(os.environ[HARNESS_ENV])
    return json.loads(path.read_text(encoding="utf-8"))


def _event_path(config: dict[str, Any], event: str) -> Path:
    return Path(config["events_dir"]) / event


def _signal_event(config: dict[str, Any], event: str, payload: str = "") -> None:
    path = _event_path(config, event)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(payload, encoding="utf-8")


def _wait_for_release(config: dict[str, Any], event: str) -> None:
    _signal_event(config, event)
    release = _event_path(config, f"release-{event}")
    deadline = time.monotonic() + 30
    while not release.exists():
        if time.monotonic() >= deadline:
            raise TimeoutError(f"timed out waiting for {release.name}")
        time.sleep(0.01)  # sase-test-wait: Poll an explicit file handshake token.


def _fake_agent(receipt_file: Path, agent_name: str, source_index: int) -> None:
    receipt_file.parent.mkdir(parents=True, exist_ok=True)
    with receipt_file.open("a", encoding="utf-8") as stream:
        stream.write(
            json.dumps(
                {
                    "agent_name": agent_name,
                    "source_index": source_index,
                    "cl_name": agent_name,
                    "pid": os.getpid(),
                }
            )
            + "\n"
        )
        stream.flush()
        os.fsync(stream.fileno())


def _run_fake_agent(receipt_file: Path, agent_name: str, source_index: int) -> None:
    subprocess.run(
        [
            sys.executable,
            str(Path(__file__).resolve()),
            "fake-agent",
            str(receipt_file),
            agent_name,
            str(source_index),
        ],
        check=True,
        env=os.environ.copy(),
    )


def _fake_launcher(prompt: str, *, extra_env: dict[str, str], **kwargs: Any) -> Any:
    del prompt
    config = _read_config()
    names = list(config["names"])
    raw_index = extra_env.get("SASE_CHOP_PROPOSAL_INDEX")
    if raw_index is None:
        name = str(extra_env.get("SASE_AGENT_PLANNED_NAME") or "")
        index = names.index(name)
    else:
        index = int(raw_index)
        name = names[index]

    request = SimpleNamespace(extra_env=extra_env)
    before = kwargs.get("before_agent_spawn")
    if before is not None:
        before(0, index, request, None)
        if config.get("hold_mode") == "before_spawn" and index == config.get(
            "hold_index"
        ):
            _wait_for_release(config, f"reserved-{index}")

    _run_fake_agent(Path(config["receipt_file"]), name, index)
    _signal_event(config, f"spawned-{index}", name)
    if config.get("hold_mode") == "after_spawn" and index == config.get("hold_index"):
        _wait_for_release(config, f"spawned-{index}")

    record = SimpleNamespace(
        agent_name=name,
        pid=10000 + index,
        workspace_num=1,
        workspace_dir=str(config["workspace"]),
        project_name="sase",
        workflow_name="fake-chop-batch-acceptance",
        cl_name=name,
        timestamp="20261118_120000",
        artifacts_dir=str(Path(config["events_dir"]) / "fake-artifacts" / name),
    )
    recorded = kwargs.get("on_agent_launch_recorded")
    if recorded is not None:
        recorded(0, index, record, None)
        _signal_event(config, f"ack-{index}", name)
        if config.get("hold_mode") == "after_ack" and index == config.get("hold_index"):
            _wait_for_release(config, f"ack-{index}")
    return [record]


def _install_lumberjack_signal_handler() -> Any:
    from sase.axe.chop_stop_signal import ChopStopSignal
    from sase.axe.lumberjack import Lumberjack

    routine = object.__new__(Lumberjack)
    routine._running = True
    routine._stop_signal = ChopStopSignal()
    routine._log = lambda *_args, **_kwargs: None
    signal.signal(signal.SIGTERM, routine._handle_shutdown)
    return routine


def _worker(operation: str) -> int:
    config = _read_config()
    routine = _install_lumberjack_signal_handler()
    if config.get("wait_start"):
        _signal_event(config, "ready")
        _wait_for_release(config, "ready")

    from sase.axe import chop_agents
    from sase.axe.chop_batch_recovery import recover_pending_chop_batches

    receipt_file = Path(config["receipt_file"])

    def _receipt_records(*_args: Any, **_kwargs: Any) -> list[Any]:
        if not receipt_file.exists():
            return []
        rows = [
            json.loads(line)
            for line in receipt_file.read_text(encoding="utf-8").splitlines()
            if line
        ]
        return [SimpleNamespace(cl_name=str(row["cl_name"])) for row in rows]

    chop_agents.get_chop_agent_records = _receipt_records

    if operation == "typed-start":
        return _typed_start(config, routine)

    from unittest.mock import patch

    from tests.workspace_lease_helpers import fake_operational_lease

    workspace = Path(config["workspace"])

    def _acquire_lease(
        project: str, *, workflow: str, holder: str, **_kwargs: object
    ) -> Any:
        return fake_operational_lease(
            workspace,
            project=project,
            workflow=f"lease({workflow})",
            holder=holder,
        )

    _signal_event(config, "ready")
    if operation not in {"ordinary", "recover"}:
        raise ValueError(f"unknown worker operation {operation!r}")
    with (
        patch(
            "sase.agent.launch_condition_workspace.acquire_operational_lease",
            _acquire_lease,
        ),
        patch(
            "sase.agent.launch_condition_workspace.release_operational_lease",
            lambda _policy: None,
        ),
    ):
        result = recover_pending_chop_batches(
            config["routine"],
            config["job"],
            launch_agents_from_cwd_fn=_fake_launcher,
            pause_requested_fn=routine._stop_signal.as_pause_fn(),
        )
    output = [
        {
            "batch_id": item.batch_id,
            "kind": item.kind,
            "launched": len(item.launched),
            "already_launched": list(item.already_launched),
            "paused": item.paused,
            "reason": item.reason,
        }
        for item in result
    ]
    _signal_event(config, "finished", json.dumps(output, sort_keys=True))
    return 0


def _typed_start(config: dict[str, Any], routine: Any) -> int:
    from unittest.mock import patch

    from sase.axe.chop_proposal_launch import launch_chop_proposals
    from sase.axe.chop_proposals import prepare_chop_proposals
    from sase.axe.state import ChopRunEntry, start_chop_run

    repo = Path(config["workspace"])
    repo.mkdir(parents=True, exist_ok=True)
    proposals = prepare_chop_proposals(
        config["job"],
        {
            "proposed_launches": [
                {
                    "id": f"proposal-{index}",
                    "prompt": (
                        f"%if::\n```bash\nexit 0\n```\nReview disposable input {index}."
                    ),
                    "workspace": "git:sase",
                    "agent_name": name,
                }
                for index, name in enumerate(config["names"])
            ]
        },
    )
    resolver = SimpleNamespace(
        workflow_type="git",
        ref="sase",
        workspace_dir=str(repo),
        project_file="/tmp/projects/sase/sase.sase",
    )
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

    from tests.workspace_lease_helpers import fake_operational_lease

    def _acquire_lease(
        project: str, *, workflow: str, holder: str, **_kwargs: object
    ) -> Any:
        return fake_operational_lease(
            repo,
            project=project,
            workflow=f"lease({workflow})",
            holder=holder,
        )

    def _batch_created(_batch_id: str) -> None:
        _signal_event(config, "ready")
        if config.get("wait_start"):
            _wait_for_release(config, "ready")

    def _launch_recorded(row: dict[str, Any]) -> None:
        _signal_event(config, f"typed-outer-{row['index']}", str(row["agent_name"]))

    with (
        patch(
            "sase.agent.launch_cwd_common.resolve_known_project_vcs_launch_ref",
            lambda _prompt: resolver,
        ),
        patch(
            "sase.agent.launch_condition_workspace.acquire_operational_lease",
            _acquire_lease,
        ),
        patch(
            "sase.agent.launch_condition_workspace.release_operational_lease",
            lambda _policy: None,
        ),
    ):
        result = launch_chop_proposals(
            lumberjack_name=config["routine"],
            chop_name=config["job"],
            run_id=config["run_id"],
            proposals=proposals,
            launch_agent_from_cwd_fn=None,
            launch_agents_from_cwd_fn=_fake_launcher,
            run_started_at=datetime.now(UTC),
            preflight=SimpleNamespace(decision={"checkpoint_key": "acceptance"}),
            batch_created_fn=_batch_created,
            launch_recorded_fn=_launch_recorded,
            pause_requested_fn=routine._stop_signal.as_pause_fn(),
        )
    _signal_event(
        config,
        "finished",
        json.dumps(
            {
                "batch_id": result.batch_id,
                "paused": result.paused,
                "admission_complete": result.admission_result.admission_complete,
            },
            sort_keys=True,
        ),
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if args and args[0] == "fake-agent":
        _fake_agent(Path(args[1]), args[2], int(args[3]))
        return 0
    if args and args[0] in {"ordinary", "recover", "typed-start"}:
        os.environ[HARNESS_ENV] = args[1]
        return _worker(args[0])
    raise SystemExit("usage: chop_batch_process_worker.py OPERATION CONFIG")


if __name__ == "__main__":
    raise SystemExit(main())
