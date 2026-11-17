"""Process-backed monitor hijack and recovery canaries."""

from __future__ import annotations

from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
import json
import os
from pathlib import Path
import shlex
import sys
from typing import Any

import pytest

from sase.ace.tui.actions.agents._hijack_decision import compute_hijack_decision
from sase.agent.hijack.ledger import load_record, load_record_by_artifacts_dir
from sase.agent.staged_handoff import read_staged_handoff
from sase.core.agent_artifact_paths import iter_agent_artifact_dirs
from sase.legacy_xprompt_names import (
    LEGACY_SUBMITTED_XPROMPT_FILENAME,
    RAW_PROMPT_FILENAME,
    SUBMITTED_PROMPT_FILENAME,
)
from sase.running_field import get_claimed_workspaces, release_workspace
from tests._load_tolerant import LOAD_TOLERANT_TIMEOUT
from tests.fakey.harness import _wait_for_condition
from tests.fakey._agent_hijack_canary_harness import CanaryHarness
from tests.fakey._agent_hijack_canary_scenarios import (
    _HijackHost,
    _dirty_workspace,
    _prompt,
)
from tests.fakey._agent_hijack_canary_support import (
    SESSION,
    WORKSPACE_NUM,
    read_json,
)

_PARTIAL_SENTINEL = "MONITOR_PARTIAL_OUTPUT_SENTINEL"
_FOLLOWUP_SENTINEL = "MONITOR_FOLLOWUP_CANARY"


def _sleep_command(started: Path, runs: Path, release: Path) -> str:
    """Build one repeatable command that records its PID and blocks on a file."""
    code = "\n".join(
        (
            "from pathlib import Path",
            "import os",
            "import time",
            f"runs = Path({str(runs)!r})",
            "with runs.open('a', encoding='utf-8') as handle:",
            "    handle.write(f'{os.getpid()}\\n')",
            f"print({_PARTIAL_SENTINEL!r}, flush=True)",
            "print('x' * 300_000, flush=True)",
            "time.sleep(0.15)",
            f"Path({str(started)!r}).touch()",
            f"release = Path({str(release)!r})",
            "while not release.exists():",
            "    time.sleep(0.05)",
        )
    )
    return f"{shlex.quote(sys.executable)} -c {shlex.quote(code)}"


def _stage_monitor(
    harness: CanaryHarness,
    launch: Any,
    *,
    command: str,
) -> tuple[str, Path, str]:
    """Stage through the production CLI and return its frozen monitor identity."""
    from sase.main.monitor.start import handle_monitor_start
    from sase.main.parser import create_parser

    starter_meta = harness.wait_meta(launch)
    with harness.monkeypatch.context() as env:
        env.setenv("SASE_AGENT", "1")
        env.setenv("SASE_AGENT_NAME", str(starter_meta["name"]))
        env.setenv("SASE_AGENT_CL_NAME", harness.project)
        env.setenv("SASE_ARTIFACTS_DIR", launch.artifacts_dir)
        args = create_parser().parse_args(
            [
                "monitor",
                "start",
                "--reason",
                "monitor hijack canary",
                "--next",
                f"Inspect the interrupted output and end with {_FOLLOWUP_SENTINEL}.",
                "--model",
                "fakey/fakey-large",
                "--start-status",
                "RUNNING",
                "--stop-status",
                "DONE",
                "--timeout",
                "180s",
                "--tail-lines",
                "4",
                "--next-output",
                "tail",
                "--",
                command,
            ]
        )
        stdout = StringIO()
        stderr = StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            code = handle_monitor_start(args)
        assert code == 0, f"monitor staging failed: {stderr.getvalue()}"

    staged = read_staged_handoff(launch.artifacts_dir)
    assert staged is not None and staged.get("kind") == "monitor", staged
    payload = staged.get("payload")
    assert isinstance(payload, dict), staged
    workspace = payload.get("workspace")
    claim_context = (
        workspace.get("claim_context") if isinstance(workspace, dict) else None
    )
    assert isinstance(claim_context, dict), payload
    artifacts_dir = Path(str(claim_context["artifacts_dir"]))
    assert artifacts_dir.is_dir(), artifacts_dir
    return str(payload["monitor_id"]), artifacts_dir, str(staged["staged_id"])


def _monitor_pid_list(path: Path) -> list[int]:
    if not path.is_file():
        return []
    return [int(line) for line in path.read_text(encoding="utf-8").splitlines()]


def _wait_monitor_running(
    *,
    monitor_id: str,
    artifacts_dir: Path,
    started: Path,
    runs: Path,
    count: int = 1,
) -> dict[str, Any]:
    """Wait for adopted monitor metadata and the actual child command barrier."""

    def ready() -> bool:
        meta_path = artifacts_dir / "agent_meta.json"
        if not meta_path.is_file() or not started.exists():
            return False
        try:
            meta = read_json(meta_path)
        except (OSError, json.JSONDecodeError):
            return False
        return (
            meta.get("monitor_id") == monitor_id
            and meta.get("monitor_state") == "running"
            and len(_monitor_pid_list(runs)) >= count
        )

    _wait_for_condition(
        ready,
        LOAD_TOLERANT_TIMEOUT,
        f"adopted monitor {monitor_id} to own its running command",
    )
    return read_json(artifacts_dir / "agent_meta.json")


def _monitor_row(harness: CanaryHarness, artifacts_dir: Path) -> Any:
    target = str(artifacts_dir.resolve())
    for row in harness.load_rows():
        getter = getattr(row, "get_artifacts_dir", None)
        if not callable(getter):
            continue
        try:
            candidate = str(getter() or "")
        except Exception:
            continue
        if candidate and str(Path(candidate).resolve()) == target:
            return row
    raise AssertionError(
        f"TUI loader omitted monitor row {artifacts_dir}\n{harness._row_summaries()}"
    )


def _session_container(harness: CanaryHarness) -> Any:
    rows = harness.load_rows()
    container = next(
        (
            row
            for row in rows
            if row.agent_name == SESSION
            or (
                getattr(row, "is_agent_session_container_row", False)
                and getattr(row, "agent_session", None) == SESSION
            )
        ),
        None,
    )
    assert container is not None, harness._row_summaries()
    return container


def _cached_tui_hijack(
    harness: CanaryHarness,
    *,
    monitor_id: str,
    artifacts_dir: Path,
) -> tuple[_HijackHost, Any, dict[str, Any]]:
    """Compare the loaded/cached TUI decision with CLI explain, then use the TUI op."""
    from sase.main.parser import create_parser
    from sase.agents.cli_hijack import handle_agents_hijack

    assert read_json(artifacts_dir / "agent_meta.json").get("monitor_id") == monitor_id
    monitor_row = _monitor_row(harness, artifacts_dir)
    assert monitor_row.workspace_num == WORKSPACE_NUM
    assert getattr(monitor_row, "agent_session_role", None) == "monitor"
    container = _session_container(harness)
    rows = harness.load_rows()
    view = compute_hijack_decision(container)
    assert view.mode == "immediate", view.decision
    assert view.decision.get("adapter") == "monitor", view.decision
    assert view.occupant_name == monitor_row.agent_name, view

    cli_args = create_parser().parse_args(
        ["agent", "hijack", "--explain", "--json", SESSION]
    )
    stdout = StringIO()
    stderr = StringIO()
    with redirect_stdout(stdout), redirect_stderr(stderr):
        code = handle_agents_hijack(cli_args)
    assert code == 0, stderr.getvalue()
    cli = json.loads(stdout.getvalue())
    assert cli["mode"] == view.mode, cli
    assert cli["adapter"] == view.decision.get("adapter"), cli
    assert cli["occupant_name"] == view.occupant_name, cli
    assert cli["workspace_num"] == WORKSPACE_NUM, cli

    host = _HijackHost(harness.root, harness.monkeypatch)
    host._agents = rows
    host._agents_with_children = rows
    host._store_hijack_decision(container, view)
    cached = host._cached_hijack_decision(container)
    assert cached is not None and cached.decision == view.decision
    assert host._start_hijack_agent(container), host.notifications
    assert host.last_payload is not None, host.notifications
    assert host.last_payload.get("hijack_id"), host.last_payload
    return host, monitor_row, dict(host.last_payload)


def _wait_hijacked(
    harness: CanaryHarness,
    *,
    monitor_id: str,
    artifacts_dir: Path,
    command_pids: list[int],
) -> tuple[dict[str, Any], dict[str, Any]]:
    done_path = artifacts_dir / "done.json"

    def settled() -> bool:
        return (
            done_path.is_file()
            and _monitor_row(harness, artifacts_dir).status == "HIJACKED"
        )

    _wait_for_condition(
        settled,
        LOAD_TOLERANT_TIMEOUT,
        f"monitor {monitor_id} to settle as HIJACKED",
    )
    done = read_json(done_path)
    record = load_record_by_artifacts_dir(str(artifacts_dir))
    assert record is not None and record.get("state") == "held", record
    assert done.get("outcome") == "hijacked", done
    assert done.get("monitor_state") == "stopped", done
    assert done.get("monitor_followup_outcome") == "hijacked", done
    assert record.get("suppressed_followup", {}).get("kind") == "monitor_followup", (
        record
    )
    assert isinstance(record.get("snapshots"), list) and record["snapshots"], record
    assert all(not _pid_alive(pid) for pid in command_pids), command_pids

    claims = [
        claim
        for claim in get_claimed_workspaces(str(harness.project_file))
        if claim.workspace_num == WORKSPACE_NUM
    ]
    assert len(claims) == 1, claims
    assert claims[0].pinned or "PINNED" in claims[0].suffix_fields, claims[0]
    assert claims[0].artifacts_timestamp == artifacts_dir.name, claims[0]
    return done, record


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def _release_test_process_claim(harness: CanaryHarness) -> None:
    """Keep harness teardown from treating its own PID as a subprocess."""
    for claim in get_claimed_workspaces(str(harness.project_file)):
        if claim.workspace_num != WORKSPACE_NUM or claim.pid != os.getpid():
            continue
        release_workspace(
            str(harness.project_file),
            claim.workspace_num,
            claim.workflow,
            claim.cl_name,
            expected_pid=os.getpid(),
            artifacts_timestamp=claim.artifacts_timestamp,
        )


def _session_members(harness: CanaryHarness) -> list[tuple[Path, dict[str, Any]]]:
    members: list[tuple[Path, dict[str, Any]]] = []
    for artifacts_dir in iter_agent_artifact_dirs(harness.project, newest_first=False):
        meta_path = artifacts_dir / "agent_meta.json"
        if not meta_path.is_file():
            continue
        try:
            meta = read_json(meta_path)
        except (OSError, json.JSONDecodeError):
            continue
        if meta.get("agent_session") == SESSION:
            members.append((artifacts_dir, meta))
    return members


def _recover(harness: CanaryHarness, name: str, action: str) -> int:
    from sase.agents.cli_recover import handle_agents_recover
    from sase.main.parser import create_parser

    argv = ["agent", "recover", "-a", action, "-j", name]
    if action == "continue":
        argv.extend(["-m", "fakey/fakey-large"])
    args = create_parser().parse_args(argv)
    stdout = StringIO()
    stderr = StringIO()
    with redirect_stdout(stdout), redirect_stderr(stderr):
        code = handle_agents_recover(args)
    harness.last_recover = (code, stdout.getvalue(), stderr.getvalue())
    return code


def _wait_recovery_successor(
    harness: CanaryHarness,
    *,
    original_name: str,
    monitor_name: str,
) -> tuple[Path, dict[str, Any]]:
    """Wait for the recovery successor to settle in the held workspace.

    Existence-only on purpose: the successor runs under fakey in the dirtied
    held workspace, and fakey cannot submit the commit-finalizer declaration a
    dirty tree requires. Sibling LLM canaries use the same convention; the
    recovery contract is proven by the resolved ledger record, the successor
    identity/workspace, and the composed prompt below — not by fakey's
    finalizer outcome.
    """
    selected: list[tuple[Path, dict[str, Any]]] = []

    def settled() -> bool:
        selected.clear()
        for artifacts_dir in iter_agent_artifact_dirs(
            harness.project, newest_first=False
        ):
            meta_path = artifacts_dir / "agent_meta.json"
            if not meta_path.is_file():
                continue
            try:
                meta = read_json(meta_path)
            except (OSError, json.JSONDecodeError):
                continue
            if (
                meta.get("name") in {original_name, monitor_name}
                or meta.get("workspace_num") != WORKSPACE_NUM
            ):
                continue
            done_path = artifacts_dir / "done.json"
            if not done_path.is_file():
                continue
            selected.append((artifacts_dir, meta))
        return len(selected) >= 1

    try:
        _wait_for_condition(
            settled,
            LOAD_TOLERANT_TIMEOUT,
            "a settled same-session recovery successor",
        )
    except TimeoutError as exc:
        raise AssertionError(
            f"{exc}\nrecover={harness.last_recover!r}\n"
            f"session members={[(str(path), meta.get('name'), meta.get('workspace_num')) for path, meta in _session_members(harness)]!r}\n"
            f"{harness.dump_all_artifacts()}"
        ) from exc
    assert len(selected) == 1, selected
    path, meta = selected[0]
    assert meta.get("agent_session") == SESSION, meta
    assert meta.get("workspace_num") == WORKSPACE_NUM, meta
    assert (
        Path(str(meta.get("workspace_dir"))).resolve()
        == Path(str(harness.workspace)).resolve()
    ), meta
    return path, meta


def _prompt_text(artifacts_dir: Path) -> str:
    path = artifacts_dir / RAW_PROMPT_FILENAME
    if path.is_file():
        return path.read_text(encoding="utf-8")
    for name in (
        SUBMITTED_PROMPT_FILENAME,
        LEGACY_SUBMITTED_XPROMPT_FILENAME,
        "followup_prompt.md",
    ):
        candidate = artifacts_dir / name
        if candidate.is_file():
            return candidate.read_text(encoding="utf-8")
    raise AssertionError(f"no saved prompt under {artifacts_dir}")


def _new_monitor_followups(
    harness: CanaryHarness,
    *,
    original_monitor_id: str,
    rerun_monitor_id: str,
) -> list[tuple[Path, dict[str, Any]]]:
    # Monitor follow-ups inherit agent_session_role "monitor" from the starter
    # identity (monitor/followup.py launches with starter_role), so role cannot
    # distinguish them from monitor members. The starter root carries the
    # original monitor id (it staged the monitor), so excluding both monitor
    # ids plus the root role isolates exactly the rerun monitor's follow-ups.
    return [
        (path, meta)
        for path, meta in _session_members(harness)
        if meta.get("agent_session_role") != "root"
        and meta.get("monitor_id") not in {original_monitor_id, rerun_monitor_id}
    ]


def test_monitor_hijack_continue_same_workspace(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    harness = CanaryHarness(tmp_path, monkeypatch)
    starter_barrier = harness.barrier("monitor-continue-starter")
    started = tmp_path / "barriers" / "monitor-continue-command.started"
    runs = tmp_path / "barriers" / "monitor-continue-command.pids"
    release = tmp_path / "barriers" / "monitor-continue-command.release"
    launch = None
    try:
        launch = harness.spawn(
            _prompt(
                directive="%id:canary",
                body="Hold while the monitor is staged for hijack.",
                barrier=starter_barrier,
            ),
            extra_env={"SASE_AGENT_PLANNED_NAME": SESSION},
        )
        harness.wait_meta(launch)
        harness.wait_barrier(launch, starter_barrier)
        monitor_id, monitor_dir, staged_id = _stage_monitor(
            harness,
            launch,
            command=_sleep_command(started, runs, release),
        )
        staged = read_staged_handoff(launch.artifacts_dir)
        assert staged is not None and staged.get("staged_id") == staged_id

        starter_barrier.open()
        starter_done = harness.wait_done(launch)
        assert starter_done.get("outcome") in {"success", "succeeded", "completed"}, (
            starter_done
        )
        meta = _wait_monitor_running(
            monitor_id=monitor_id,
            artifacts_dir=monitor_dir,
            started=started,
            runs=runs,
        )
        assert meta.get("workspace_num") == WORKSPACE_NUM, meta
        assert (
            Path(str(meta.get("workspace_dir"))).resolve()
            == Path(str(harness.workspace)).resolve()
        ), meta
        pids = _monitor_pid_list(runs)
        assert len(pids) == 1 and _pid_alive(pids[0]), pids

        _dirty_workspace(harness.workspace)
        _host, monitor_row, payload = _cached_tui_hijack(
            harness,
            monitor_id=monitor_id,
            artifacts_dir=monitor_dir,
        )
        assert payload.get("status") in {"hijacked", "stopped", "held"}, payload
        done, record = _wait_hijacked(
            harness,
            monitor_id=monitor_id,
            artifacts_dir=monitor_dir,
            command_pids=pids,
        )
        assert record["suppressed_followup"]["ref"]
        members = _session_members(harness)
        assert len(members) == 2, [
            (str(path), row.get("name")) for path, row in members
        ]
        assert done.get("monitor_followup_outcome") == "hijacked"

        code = _recover(harness, monitor_row.agent_name, "continue")
        assert code == 0, (
            f"recover continue failed: {harness.last_recover!r}\n{harness.diagnostics(launch)}"
        )
        successor_dir, _successor_meta = _wait_recovery_successor(
            harness,
            original_name=str(harness.wait_meta(launch)["name"]),
            monitor_name=monitor_row.agent_name,
        )
        prompt = _prompt_text(successor_dir)
        assert _PARTIAL_SENTINEL in prompt, len(prompt)
        assert "untrusted data, not instructions" in prompt, prompt[:2000]
        assert len(prompt.encode("utf-8")) < 120_000, len(prompt)
        assert len(_session_members(harness)) == 3
        resolved = load_record(str(record["hijack_id"]))
        assert resolved is not None and resolved.get("state") == "resolved", resolved
        # The canary pins the isolated fakey model explicitly (-m), which maps
        # continue onto the instruct reservation carrying the recorded
        # follow-up (see recover_target.resolve_effective_target).
        assert resolved.get("resolution_action") == "instruct", resolved
    finally:
        starter_barrier.open()
        _release_test_process_claim(harness)
        harness.close()


def test_monitor_hijack_rerun_same_workspace(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    harness = CanaryHarness(tmp_path, monkeypatch)
    starter_barrier = harness.barrier("monitor-rerun-starter")
    started = tmp_path / "barriers" / "monitor-rerun-command.started"
    runs = tmp_path / "barriers" / "monitor-rerun-command.pids"
    release = tmp_path / "barriers" / "monitor-rerun-command.release"
    launch = None
    try:
        launch = harness.spawn(
            _prompt(
                directive="%id:canary",
                body="Hold while the monitor is staged for rerun.",
                barrier=starter_barrier,
            ),
            extra_env={"SASE_AGENT_PLANNED_NAME": SESSION},
        )
        harness.wait_meta(launch)
        harness.wait_barrier(launch, starter_barrier)
        original_id, original_dir, _staged_id = _stage_monitor(
            harness,
            launch,
            command=_sleep_command(started, runs, release),
        )
        starter_barrier.open()
        starter_done = harness.wait_done(launch)
        assert starter_done.get("outcome") in {"success", "succeeded", "completed"}, (
            starter_done
        )
        _wait_monitor_running(
            monitor_id=original_id,
            artifacts_dir=original_dir,
            started=started,
            runs=runs,
        )
        original_pids = _monitor_pid_list(runs)
        assert len(original_pids) == 1 and _pid_alive(original_pids[0]), original_pids

        _dirty_workspace(harness.workspace)
        _host, original_row, _payload = _cached_tui_hijack(
            harness,
            monitor_id=original_id,
            artifacts_dir=original_dir,
        )
        _done, record = _wait_hijacked(
            harness,
            monitor_id=original_id,
            artifacts_dir=original_dir,
            command_pids=original_pids,
        )
        assert _recover(harness, original_row.agent_name, "rerun") == 0, (
            f"recover rerun failed: {harness.last_recover!r}\n{harness.diagnostics(launch)}"
        )

        def rerun_started() -> bool:
            return len(_monitor_pid_list(runs)) >= 2 and started.exists()

        _wait_for_condition(
            rerun_started,
            LOAD_TOLERANT_TIMEOUT,
            "one new monitor command in the held workspace",
        )
        rerun_pids = _monitor_pid_list(runs)
        assert len(rerun_pids) == 2, rerun_pids
        assert not _pid_alive(original_pids[0]), original_pids
        assert _pid_alive(rerun_pids[1]), rerun_pids

        rerun_dirs: list[tuple[Path, dict[str, Any]]] = []

        def rerun_member_ready() -> bool:
            rerun_dirs.clear()
            for artifacts_dir in iter_agent_artifact_dirs(
                harness.project, newest_first=False
            ):
                meta_path = artifacts_dir / "agent_meta.json"
                if not meta_path.is_file():
                    continue
                try:
                    meta = read_json(meta_path)
                except (OSError, json.JSONDecodeError):
                    continue
                if (
                    meta.get("agent_session_role") == "monitor"
                    and meta.get("monitor_id") != original_id
                    and meta.get("agent_session") == SESSION
                ):
                    rerun_dirs.append((artifacts_dir, meta))
            return len(rerun_dirs) == 1

        _wait_for_condition(
            rerun_member_ready,
            LOAD_TOLERANT_TIMEOUT,
            "the rerun monitor member to be indexed",
        )
        rerun_dir, rerun_meta = rerun_dirs[0]
        rerun_id = str(rerun_meta["monitor_id"])
        assert rerun_id != original_id, rerun_meta
        descriptor_ref = record["suppressed_followup"]["ref"]
        descriptor = read_json(Path(str(descriptor_ref)))
        assert rerun_meta.get("monitor_command") == descriptor.get("command"), {
            "rerun": rerun_meta.get("monitor_command"),
            "descriptor": descriptor.get("command"),
        }
        assert rerun_meta.get("workspace_num") == WORKSPACE_NUM, rerun_meta
        assert (
            Path(str(rerun_meta.get("workspace_dir"))).resolve()
            == Path(str(harness.workspace)).resolve()
        ), rerun_meta
        assert rerun_meta.get("monitor_followup_outcome") in {None, "pending"}, (
            rerun_meta
        )

        release.touch()

        def followup_done() -> bool:
            meta = read_json(rerun_dir / "agent_meta.json")
            done_path = rerun_dir / "done.json"
            if not done_path.is_file():
                return False
            done = read_json(done_path)
            return (
                done.get("monitor_state") == "completed"
                and done.get("monitor_followup_outcome") in {"launched", "settled"}
            ) or meta.get("monitor_followup_outcome") in {"launched", "settled"}

        _wait_for_condition(
            followup_done,
            LOAD_TOLERANT_TIMEOUT,
            "the rerun monitor to finish and deliver its ordinary follow-up",
        )
        _wait_for_condition(
            lambda: (
                len(
                    _new_monitor_followups(
                        harness,
                        original_monitor_id=original_id,
                        rerun_monitor_id=rerun_id,
                    )
                )
                == 1
            ),
            LOAD_TOLERANT_TIMEOUT,
            "exactly one follow-up from the rerun monitor",
        )
        followers = _new_monitor_followups(
            harness,
            original_monitor_id=original_id,
            rerun_monitor_id=rerun_id,
        )
        assert len(followers) == 1, followers
        assert all(
            meta.get("workspace_num") == WORKSPACE_NUM for _path, meta in followers
        ), followers
        original = load_record(str(record["hijack_id"]))
        assert original is not None and original.get("state") == "resolved", original
        assert original.get("resolution_action") == "rerun", original
        original_done = read_json(original_dir / "done.json")
        assert original_done.get("monitor_followup_outcome") == "hijacked", (
            original_done
        )
        assert len(_session_members(harness)) == 4
    finally:
        starter_barrier.open()
        _release_test_process_claim(harness)
        harness.close()
