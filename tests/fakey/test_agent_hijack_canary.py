"""Real-pipeline Agent Hijack canary.

Launches through ``spawn_agent_subprocess`` so bootstrap, anonymous ``tmp_*``
workflow creation, and directive extraction all run for real. Fakey holds on a
barrier until the TUI loader sees RUNNING with an ``immediate`` decision, then
hijacks through ``submit_agent_hijack`` → ``sase agent persist-hijack``.
Continue uses ``sase agent recover``.
"""

from __future__ import annotations

from io import StringIO
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
from types import SimpleNamespace
from typing import Any

import pytest
import yaml  # type: ignore[import-untyped]

from sase.ace.tui.actions.agent_durable import submit_agent_hijack
from sase.ace.tui.actions.agents._hijack_action import AgentHijackActionMixin
from sase.ace.tui.actions.agents._hijack_decision import compute_hijack_decision
from sase.ace.tui.actions.agents._loading_helpers import (
    load_agents_from_disk_with_state,
)
from sase.ace.tui.models import Agent
from sase.agent.agent_session_attach import prepare_agent_session_attach_launch
from sase.agent.hijack.facts import resolve_and_decide
from sase.agent.hijack.ledger import load_record, load_record_by_artifacts_dir
from sase.agent.launch_executor_types import LaunchExecutionContext
from sase.agent.launcher import spawn_agent_subprocess
from sase.agent.launch_types import AgentLaunchResult
from sase.config import _cache as config_cache
from sase.core.agent_artifact_paths import iter_agent_artifact_dirs
from sase.core.agent_launch_facade import _allocate_launch_timestamp_batch
from sase.ops import (
    DurableOperationRequest,
    read_operation_result,
    write_operation_request,
)
from sase.ops.names import AGENT_PERSIST_HIJACK
from sase.running_field import get_claimed_workspaces
from tests._load_tolerant import LOAD_TOLERANT_TIMEOUT
from tests._prettier_fakes import hide_prettier_from_path
from tests.fakey.harness import FakeyBarrier, _wait_for_condition

_PROJECT = "hijack-canary"
_WORKSPACE_NUM = 3
_SESSION = "canary"
_POLL = 0.05


def _git(root: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(root), *args],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    return result.stdout.strip()


def _init_repo(root: Path) -> None:
    root.mkdir(parents=True, exist_ok=True)
    _git(root, "init")
    _git(root, "config", "user.name", "Hijack Canary")
    _git(root, "config", "user.email", "hijack-canary@example.invalid")
    (root / "README.md").write_text("canary base\n", encoding="utf-8")
    _git(root, "add", "README.md")
    _git(root, "commit", "-m", "base")
    remote = root.with_name(f"{root.name}.git")
    remote.mkdir()
    subprocess.run(
        ["git", "init", "--bare", str(remote)],
        capture_output=True,
        text=True,
        check=True,
    )
    _git(root, "remote", "add", "origin", str(remote))
    _git(root, "push", "-u", "origin", "HEAD")


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def _kill_tree(pid: int) -> None:
    if pid <= 0:
        return
    try:
        os.killpg(pid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError, OSError):
        try:
            os.kill(pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError, OSError):
            pass


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _prompt(*, directive: str, body: str, barrier: FakeyBarrier | None) -> str:
    header = f"{directive.rstrip()}\n" if directive.strip() else ""
    if barrier is None:
        scenario = "reply: canary settled\n"
    else:
        scenario = yaml.safe_dump(
            {
                "steps": barrier.steps(),
                "reply": "canary recovered",
            },
            sort_keys=False,
        )
    return f"{header}%model:fakey-large\n{body}\n\n```fakey\n{scenario.rstrip()}\n```\n"


class _HijackHost(AgentHijackActionMixin):
    """TUI hijack ingress that runs persist-hijack on the calling thread."""

    def __init__(self, root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        self.root = root
        self._monkeypatch = monkeypatch
        self._agents: list[Agent] = []
        self._agents_with_children: list[Agent] = []
        self.notifications: list[tuple[str, str]] = []
        self.current_idx = 0

    def notify(self, message: str, *, severity: str = "information") -> None:
        self.notifications.append((message, severity))

    def _refresh_agents_display(
        self, *, list_changed: bool = False, defer_detail: bool = False
    ) -> None:
        del list_changed, defer_detail

    def _submit_durable_proc(self, argv: Any, **kwargs: Any) -> SimpleNamespace:
        del argv
        request_path = self.root / "persist-hijack-request.json"
        result_path = self.root / "persist-hijack-result.json"
        payload = dict(kwargs["request"])
        write_operation_request(
            request_path,
            DurableOperationRequest(
                operation=str(kwargs["operation"]),
                payload=payload,
            ),
        )
        from sase.main.parser import create_parser
        from sase.ops.commands.agent import handle_agent_operation

        self._monkeypatch.setenv("SASE_PROC_ID", "hijack-canary")
        args = create_parser().parse_args(
            [
                "agent",
                "persist-hijack",
                "-Q",
                str(request_path),
                "-R",
                str(result_path),
            ]
        )
        code = handle_agent_operation(args)
        loaded = read_operation_result(
            result_path,
            expected_operation=AGENT_PERSIST_HIJACK,
            expected_proc_id="hijack-canary",
        )
        on_complete = kwargs.get("on_complete")
        if callable(on_complete):
            on_complete(
                SimpleNamespace(
                    payload=dict(loaded.payload or {}),
                    message=loaded.message,
                    success=loaded.success and code == 0,
                )
            )
        assert loaded.success and code == 0, (
            f"persist-hijack failed: code={code} message={loaded.message!r} "
            f"error={loaded.error!r} payload={loaded.payload!r}"
        )
        return SimpleNamespace(proc_id="hijack-canary")


class _CanaryHarness:
    """Isolated home, git workspace, fakey binary, and real runner launches."""

    def __init__(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        self.root = tmp_path
        self.monkeypatch = monkeypatch
        self.home = tmp_path / "sase-home"
        self.primary = tmp_path / "primary"
        self.state_dir = tmp_path / "fakey-state"
        self.project_dir = self.home / "projects" / _PROJECT
        self.project_file = self.project_dir / f"{_PROJECT}.sase"
        self.pids: list[int] = []
        self._stamps: set[str] = set()
        self.last_recover: tuple[int, str, str] | None = None

        fakey_binary = Path(sys.executable).with_name("fakey")
        assert fakey_binary.is_file(), (
            "just install-venv must register the fakey binary"
        )

        self.project_dir.mkdir(parents=True, exist_ok=True)
        self.state_dir.mkdir(parents=True, exist_ok=True)
        _init_repo(self.primary)
        self.project_file.write_text(
            f"WORKSPACE_DIR: {self.primary}\nNAME: {_PROJECT}\nRUNNING:\n\n",
            encoding="utf-8",
        )
        (self.primary / "sase.yml").write_text(
            yaml.safe_dump(
                {
                    "max_running_agents": 8,
                    "llm_provider": {
                        "retry": {
                            "fakey": {
                                "max_retries": 0,
                                "wait_times": [0],
                                "spawn_new_agent": False,
                            }
                        }
                    },
                },
                sort_keys=False,
            ),
            encoding="utf-8",
        )
        _git(self.primary, "add", "sase.yml")
        _git(self.primary, "commit", "-m", "project config")
        _git(self.primary, "push")

        monkeypatch.setenv("SASE_HOME", str(self.home))
        monkeypatch.setenv("SASE_TMPDIR", str(tmp_path / "tmp"))
        monkeypatch.setenv("SASE_FAKEY_PATH", str(fakey_binary))
        monkeypatch.setenv("FAKEY_STATE_DIR", str(self.state_dir))
        monkeypatch.delenv("FAKEY_SCENARIO", raising=False)
        monkeypatch.delenv("SASE_ARTIFACTS_DIR", raising=False)
        hide_prettier_from_path(monkeypatch, stub_dir=tmp_path / "hide-prettier")
        monkeypatch.chdir(self.primary)
        monkeypatch.setattr(config_cache, "include_local_config", True)
        self._write_owner_identity()
        self._allow_fakey_recovery_target()

        from sase.workspace_provider.utils import ensure_workspace_checkout

        self.workspace = Path(
            ensure_workspace_checkout(
                str(self.primary),
                _WORKSPACE_NUM,
                project_file=str(self.project_file),
            )
        )
        assert self.workspace.is_dir()

    def _write_owner_identity(self) -> None:
        from sase.config import core as config_core

        (self.home / "machine_name").write_text("athena\n", encoding="utf-8")
        config_dir = Path(config_core.CONFIG_DIR)
        config_dir.mkdir(parents=True, exist_ok=True)
        (config_dir / "sase_athena.yml").write_text(
            "id:\n  username: alice\n  machine_name: athena\n",
            encoding="utf-8",
        )
        config_core.clear_config_cache()
        from sase.llm_provider.registry import _provider_cli_available

        _provider_cli_available.cache_clear()

    def _allow_fakey_recovery_target(self) -> None:
        """Keep fakey pinned through recover in this isolated home.

        Isolated CONFIG_DIR overlays drop host provider routing, so the
        keep-work validator would otherwise refuse the same fakey target
        the occupant just ran.
        """
        from sase.agent.hijack import _recovery_admission_dispatcher as dispatcher
        from sase.llm_provider import model_alias_resolution_types as alias_types

        original = alias_types.resolved_target_is_available

        def fakey_available(target: str, **kwargs: Any) -> bool:
            provider = str(target).split("/", 1)[0].split("@", 1)[0]
            if provider == "fakey":
                return True
            return original(target, **kwargs)

        self.monkeypatch.setattr(
            alias_types, "resolved_target_is_available", fakey_available
        )
        self.monkeypatch.setattr(
            dispatcher,
            "_target_available",
            lambda target: (
                (True, None)
                if str(target).split("/", 1)[0].split("@", 1)[0] == "fakey"
                else (False, f"provider/model {target} is unavailable")
            ),
        )

    def close(self) -> None:
        for pid in list(self.pids):
            _kill_tree(pid)
        try:
            claims = get_claimed_workspaces(str(self.project_file))
        except Exception:
            claims = []
        for claim in claims:
            _kill_tree(int(claim.pid))

    def barrier(self, name: str) -> FakeyBarrier:
        barrier_dir = self.root / "barriers"
        return FakeyBarrier(
            started=barrier_dir / f"{name}.started",
            release=barrier_dir / f"{name}.release",
            timeout=LOAD_TOLERANT_TIMEOUT,
        )

    def _timestamp(self) -> str:
        after = max(self._stamps) if self._stamps else None
        stamp = _allocate_launch_timestamp_batch(1, after_timestamp=after)[0]
        self._stamps.add(stamp)
        return stamp

    def spawn(
        self,
        prompt: str,
        *,
        extra_env: dict[str, str] | None = None,
    ) -> AgentLaunchResult:
        timestamp = self._timestamp()
        context = LaunchExecutionContext(
            cl_name=_PROJECT,
            project_file=str(self.project_file),
            project_name=_PROJECT,
            workspace_dir=str(self.workspace),
            workspace_num=_WORKSPACE_NUM,
            use_preallocated_workspace=True,
        )
        context, prepared_env = prepare_agent_session_attach_launch(
            prompt, context, extra_env
        )
        workspace_dir = context.workspace_dir or str(self.workspace)
        workspace_num = (
            context.workspace_num
            if context.workspace_num is not None
            else _WORKSPACE_NUM
        )
        launch = spawn_agent_subprocess(
            cl_name=context.cl_name,
            project_file=str(self.project_file),
            workspace_dir=workspace_dir,
            workspace_num=workspace_num,
            workflow_name=f"ace(run)-{timestamp}",
            prompt=prompt,
            timestamp=timestamp,
            project_name=_PROJECT,
            extra_env=prepared_env,
            deferred_workspace=context.deferred_workspace,
        )
        self.pids.append(launch.pid)
        return launch

    def diagnostics(self, launch: AgentLaunchResult) -> str:
        chunks: list[str] = [f"pid={launch.pid} alive={_pid_alive(launch.pid)}"]
        output = Path(launch.output_path)
        if output.is_file():
            chunks.append(f"output:\n{output.read_text(encoding='utf-8')[-4000:]}")
        meta = Path(launch.artifacts_dir) / "agent_meta.json"
        if meta.is_file():
            chunks.append(f"meta:\n{meta.read_text(encoding='utf-8')}")
        done = Path(launch.artifacts_dir) / "done.json"
        if done.is_file():
            chunks.append(f"done:\n{done.read_text(encoding='utf-8')}")
        chunks.append(self.dump_all_artifacts())
        return "\n".join(chunks)

    def dump_all_artifacts(self) -> str:
        chunks: list[str] = ["=== all artifact dirs ==="]
        for artifacts_dir in iter_agent_artifact_dirs(_PROJECT, newest_first=False):
            names = sorted(path.name for path in artifacts_dir.iterdir())
            chunks.append(f"{artifacts_dir}: {names}")
            for name in (
                "agent_meta.json",
                "done.json",
                "hijack_recovery_ack.json",
                "error.json",
                "error_report.md",
            ):
                path = artifacts_dir / name
                if path.is_file():
                    text = path.read_text(encoding="utf-8")[-3000:]
                    chunks.append(f"-- {name} --\n{text}")
            for candidate in ("output.txt", "agent_output.txt", "stdout.log"):
                path = artifacts_dir / candidate
                if path.is_file():
                    chunks.append(
                        f"-- {candidate} --\n{path.read_text(encoding='utf-8')[-4000:]}"
                    )
                    break
        return "\n".join(chunks)

    def wait_meta(self, launch: AgentLaunchResult) -> dict[str, Any]:
        meta_path = Path(launch.artifacts_dir) / "agent_meta.json"

        def ready() -> bool:
            if meta_path.is_file():
                try:
                    payload = _read_json(meta_path)
                except (OSError, json.JSONDecodeError):
                    return False
                name = payload.get("name")
                return isinstance(name, str) and bool(name)
            if not _pid_alive(launch.pid):
                raise AssertionError(
                    "runner exited before writing agent_meta.json\n"
                    + self.diagnostics(launch)
                )
            return False

        _wait_for_condition(
            ready, LOAD_TOLERANT_TIMEOUT, "runner agent_meta.json with a name"
        )
        return _read_json(meta_path)

    def wait_barrier(self, launch: AgentLaunchResult, barrier: FakeyBarrier) -> None:
        def started_or_dead() -> bool:
            if barrier.started.exists():
                return True
            if not _pid_alive(launch.pid):
                raise AssertionError(
                    f"runner exited before fakey signalled {barrier.started}\n"
                    + self.diagnostics(launch)
                )
            return False

        _wait_for_condition(
            started_or_dead,
            LOAD_TOLERANT_TIMEOUT,
            f"fakey barrier {barrier.started}",
        )

    def wait_done(self, launch: AgentLaunchResult) -> dict[str, Any]:
        done_path = Path(launch.artifacts_dir) / "done.json"

        def finished() -> bool:
            if done_path.is_file():
                return True
            return False

        _wait_for_condition(
            finished, LOAD_TOLERANT_TIMEOUT, f"done.json at {done_path}"
        )
        return _read_json(done_path)

    def load_rows(self) -> list[Agent]:
        result = load_agents_from_disk_with_state(
            set(),
            full_history=True,
            use_artifact_index=False,
            source="hijack-canary",
        )
        rows: list[Agent] = []
        for row in result.all_agents:
            rows.append(row)
            rows.extend(row.followup_agents)
        return rows

    def _row_summaries(self) -> str:
        parts: list[str] = []
        for row in self.load_rows():
            artifacts = ""
            getter = getattr(row, "get_artifacts_dir", None)
            if callable(getter):
                try:
                    artifacts = str(getter() or "")
                except Exception:
                    artifacts = ""
            parts.append(
                f"{row.agent_name!r} status={row.status!r} "
                f"session={getattr(row, 'agent_session', None)!r} "
                f"artifacts={artifacts}"
            )
        return "\n".join(parts) or "<no TUI rows>"

    def row_for_launch(self, launch: AgentLaunchResult) -> Agent:
        target = str(Path(launch.artifacts_dir).resolve())
        found: list[Agent] = []

        def located() -> bool:
            found.clear()
            for row in self.load_rows():
                getter = getattr(row, "get_artifacts_dir", None)
                artifacts = ""
                if callable(getter):
                    try:
                        artifacts = str(getter() or "")
                    except Exception:
                        artifacts = ""
                if artifacts and str(Path(artifacts).resolve()) == target:
                    found.append(row)
                    return True
                if row.agent_name and str(Path(launch.artifacts_dir).name) in (
                    row.agent_name,
                    str(getattr(row, "raw_suffix", "") or ""),
                ):
                    found.append(row)
                    return True
            return False

        try:
            _wait_for_condition(
                located, LOAD_TOLERANT_TIMEOUT, f"TUI row for {launch.artifacts_dir}"
            )
        except TimeoutError as exc:
            raise TimeoutError(
                f"{exc}\n{self._row_summaries()}\n{self.diagnostics(launch)}"
            ) from exc
        return found[0]

    def wait_status(self, launch: AgentLaunchResult, status: str) -> Agent:
        found: list[Agent] = []
        target = str(Path(launch.artifacts_dir).resolve())

        def matches() -> bool:
            found.clear()
            for row in self.load_rows():
                getter = getattr(row, "get_artifacts_dir", None)
                artifacts = ""
                if callable(getter):
                    try:
                        artifacts = str(getter() or "")
                    except Exception:
                        artifacts = ""
                same_dir = bool(artifacts) and str(Path(artifacts).resolve()) == target
                if same_dir and row.status == status:
                    found.append(row)
                    return True
            return False

        try:
            _wait_for_condition(
                matches,
                LOAD_TOLERANT_TIMEOUT,
                f"TUI row for {launch.artifacts_dir} status {status}",
            )
        except TimeoutError as exc:
            raise TimeoutError(
                f"{exc}\n{self._row_summaries()}\n{self.diagnostics(launch)}"
            ) from exc
        return found[0]

    def hijack(
        self, name: str, row: Agent, *, tui_row: Agent | None = None
    ) -> dict[str, Any]:
        decision = compute_hijack_decision(row)
        assert decision.mode == "immediate", (
            f"expected immediate hijack, got {decision.decision!r}"
        )
        host = _HijackHost(self.root, self.monkeypatch)
        rows = self.load_rows()
        host._agents = rows
        host._agents_with_children = rows
        target = tui_row or row
        host._store_hijack_decision(target, decision)
        if name != (decision.occupant_name or target.agent_name):
            submitted = submit_agent_hijack(
                host,
                name=name,
                identity=str(target.identity),
                cl_name=target.cl_name,
                project_file=target.project_file or str(self.project_file),
                display_name=f"Hijack {name}",
                session_name=name,
            )
            assert submitted, (
                f"TUI persist-hijack did not submit: {host.notifications!r}"
            )
        else:
            assert host._start_hijack_agent(target), (
                f"TUI hijack ingress failed: {host.notifications!r} "
                f"decision={decision.decision!r}"
            )
        return decision.decision

    def recover_continue(self, name: str) -> int:
        from contextlib import redirect_stderr, redirect_stdout

        from sase.agents.cli_recover import handle_agents_recover
        from sase.main.parser import create_parser

        args = create_parser().parse_args(
            [
                "agent",
                "recover",
                "-a",
                "continue",
                "-m",
                "fakey/fakey-large",
                "-j",
                name,
            ]
        )
        stdout = StringIO()
        stderr = StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            code = handle_agents_recover(args)
        self.last_recover = (code, stdout.getvalue(), stderr.getvalue())
        return code

    def pinned_claim(self) -> Any:
        claims = get_claimed_workspaces(str(self.project_file))
        numbered = [claim for claim in claims if claim.workspace_num == _WORKSPACE_NUM]
        assert numbered, f"no claim for workspace #{_WORKSPACE_NUM}: {claims!r}"
        return numbered[0]


def _dirty_workspace(workspace: Path) -> None:
    (workspace / "canary-work.txt").write_text("held work\n", encoding="utf-8")


def test_anonymous_tmp_workflow_hijack_continue_same_workspace(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    harness = _CanaryHarness(tmp_path, monkeypatch)
    barrier = harness.barrier("anon")
    launch: AgentLaunchResult | None = None
    try:
        launch = harness.spawn(
            _prompt(
                directive="",
                body="Hold until the canary hijacks this anonymous turn.",
                barrier=barrier,
            )
        )
        meta = harness.wait_meta(launch)
        agent_name = str(meta["name"])
        assert agent_name
        harness.wait_barrier(launch, barrier)
        row = harness.row_for_launch(launch)
        assert row.status in {"RUNNING", "STARTING", "RETRYING"}, (
            harness._row_summaries()
        )
        assert row.workspace_num == _WORKSPACE_NUM
        _dirty_workspace(harness.workspace)
        harness.hijack(agent_name, row)
        done = harness.wait_done(launch)
        assert done.get("outcome") == "hijacked", done

        hijacked = harness.wait_status(launch, "HIJACKED")
        claim = harness.pinned_claim()
        assert claim.pinned or "PINNED" in claim.suffix_fields
        record = None
        if hijacked.hijack_id:
            record = load_record(str(hijacked.hijack_id))
        if record is None:
            record = load_record_by_artifacts_dir(str(launch.artifacts_dir))
        assert record is not None
        snapshots = record.get("snapshots")
        assert isinstance(snapshots, list) and snapshots, record

        barrier.open()
        code = harness.recover_continue(agent_name)
        assert code == 0, (
            f"recover continue failed: {harness.last_recover!r}\n"
            + harness.diagnostics(launch)
        )

        def successor_settled() -> bool:
            for artifacts_dir in iter_agent_artifact_dirs(_PROJECT, newest_first=False):
                meta_path = artifacts_dir / "agent_meta.json"
                if not meta_path.is_file():
                    continue
                try:
                    child = _read_json(meta_path)
                except (OSError, json.JSONDecodeError):
                    continue
                if child.get("name") == agent_name:
                    continue
                if int(child.get("workspace_num") or 0) != _WORKSPACE_NUM:
                    continue
                if child.get("pid"):
                    harness.pids.append(int(child["pid"]))
                done = artifacts_dir / "done.json"
                if not done.is_file():
                    continue
                try:
                    payload = _read_json(done)
                except (OSError, json.JSONDecodeError):
                    continue
                if payload.get("outcome") in {"success", "hijacked", "completed"}:
                    return True
            return False

        _wait_for_condition(
            successor_settled,
            LOAD_TOLERANT_TIMEOUT,
            "recovery successor to settle in the same workspace",
        )
        continued = harness.wait_status(launch, "CONTINUED")
        assert continued.workspace_num == _WORKSPACE_NUM
    finally:
        barrier.open()
        harness.close()


def test_session_hijack_chooses_running_member_one(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    harness = _CanaryHarness(tmp_path, monkeypatch)
    barrier = harness.barrier("member")
    parent: AgentLaunchResult | None = None
    child: AgentLaunchResult | None = None
    try:
        parent = harness.spawn(
            _prompt(
                directive="%id:canary",
                body="Finish so member --1 can take the workspace.",
                barrier=None,
            ),
            extra_env={"SASE_AGENT_PLANNED_NAME": _SESSION},
        )
        parent_done = harness.wait_done(parent)
        assert parent_done.get("outcome") in {"success", "completed"}, (
            harness.diagnostics(parent)
        )

        child = harness.spawn(
            _prompt(
                directive="%id(1, session=canary)",
                body="Hold the session claim until hijacked.",
                barrier=barrier,
            ),
            extra_env={"SASE_AGENT_PLANNED_NAME": f"{_SESSION}--1"},
        )
        child_meta = harness.wait_meta(child)
        member_name = str(child_meta["name"])
        assert member_name.endswith("--1"), child_meta
        harness.wait_barrier(child, barrier)
        member_row = harness.row_for_launch(child)
        assert member_row.status in {"RUNNING", "STARTING", "RETRYING"}, (
            harness._row_summaries()
        )

        subject, decision = resolve_and_decide(_SESSION)
        assert subject.occupant_name == member_name, (
            f"resolver occupant={subject.occupant_name!r} reason={subject.occupant_reason!r} "
            f"decision={decision!r}"
        )
        assert decision.get("mode") == "immediate", decision

        session_row = member_row
        for row in harness.load_rows():
            if row.agent_name == _SESSION or (
                getattr(row, "is_agent_session_container_row", False)
                and getattr(row, "agent_session", None) == _SESSION
            ):
                session_row = row
                break
        _dirty_workspace(harness.workspace)
        harness.hijack(_SESSION, session_row)
        harness.wait_status(child, "HIJACKED")
        claim = harness.pinned_claim()
        assert claim.pinned or "PINNED" in claim.suffix_fields
    finally:
        barrier.open()
        harness.close()
