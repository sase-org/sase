"""Isolated process-backed harness for the Agent Hijack canary scenarios."""

from __future__ import annotations

import os
from pathlib import Path
import signal
import subprocess
import sys

import pytest
import yaml  # type: ignore[import-untyped]

from sase.ace.tui.actions.agents._loading_helpers import (
    load_agents_from_disk_with_state,
)
from sase.ace.tui.models import Agent
from sase.agent.agent_session_attach import prepare_agent_session_attach_launch
from sase.agent.launch_executor_types import LaunchExecutionContext
from sase.agent.launcher import spawn_agent_subprocess
from sase.agent.launch_types import AgentLaunchResult
from sase.config import _cache as config_cache
from sase.core.agent_artifact_paths import iter_agent_artifact_dirs
from sase.core.agent_launch_facade import _allocate_launch_timestamp_batch
from sase.running_field import get_claimed_workspaces
from tests._load_tolerant import LOAD_TOLERANT_TIMEOUT
from tests._prettier_fakes import hide_prettier_from_path
from tests.fakey.harness import FakeyBarrier, _wait_for_condition
from tests.fakey._agent_hijack_canary_support import (
    PROJECT,
    WORKSPACE_NUM,
    read_json,
)


def _finalizer_complete_path(barrier: FakeyBarrier) -> Path:
    return barrier.started.with_suffix(".finished")


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


class CanaryHarness:
    """Isolated home, git workspace, fakey binary, and real runner launches."""

    def __init__(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        *,
        finalizer_barrier: FakeyBarrier | None = None,
    ) -> None:
        self.root = tmp_path
        self.monkeypatch = monkeypatch
        self.home = tmp_path / "sase-home"
        self.primary = tmp_path / "primary"
        self.state_dir = tmp_path / "fakey-state"
        self.project_dir = self.home / "projects" / PROJECT
        self.project_file = self.project_dir / f"{PROJECT}.sase"
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
            f"WORKSPACE_DIR: {self.primary}\nNAME: {PROJECT}\nRUNNING:\n\n",
            encoding="utf-8",
        )
        project_config: dict[str, object] = {
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
        }
        if finalizer_barrier is not None:
            complete = _finalizer_complete_path(finalizer_barrier)
            finalizer_code = "\n".join(
                (
                    "from pathlib import Path",
                    "import time",
                    f"started = Path({str(finalizer_barrier.started)!r})",
                    f"release = Path({str(finalizer_barrier.release)!r})",
                    f"complete = Path({str(complete)!r})",
                    "started.parent.mkdir(parents=True, exist_ok=True)",
                    "started.write_text('started\\n', encoding='utf-8')",
                    f"deadline = time.monotonic() + {finalizer_barrier.timeout!r}",
                    "while not release.exists() and time.monotonic() < deadline:",
                    "    time.sleep(0.01)",
                    "if not release.exists():",
                    "    raise SystemExit('finalizer barrier timed out')",
                    "complete.write_text('finalized\\n', encoding='utf-8')",
                )
            )
            project_config["finalizers"] = {
                "defaults": ["canary-barrier"],
                "instances": {
                    "canary-barrier": {
                        "use": "builtin@command",
                        "config": {
                            "command": [sys.executable, "-c", finalizer_code],
                            "cwd": "primary",
                            "timeout": f"{int(finalizer_barrier.timeout) + 30}s",
                            "submission": "none",
                        },
                    }
                },
            }
        (self.primary / "sase.yml").write_text(
            yaml.safe_dump(project_config, sort_keys=False),
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
                WORKSPACE_NUM,
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
            cl_name=PROJECT,
            project_file=str(self.project_file),
            project_name=PROJECT,
            workspace_dir=str(self.workspace),
            workspace_num=WORKSPACE_NUM,
            use_preallocated_workspace=True,
        )
        context, prepared_env = prepare_agent_session_attach_launch(
            prompt, context, extra_env
        )
        workspace_dir = context.workspace_dir or str(self.workspace)
        workspace_num = (
            context.workspace_num
            if context.workspace_num is not None
            else WORKSPACE_NUM
        )
        launch = spawn_agent_subprocess(
            cl_name=context.cl_name,
            project_file=str(self.project_file),
            workspace_dir=workspace_dir,
            workspace_num=workspace_num,
            workflow_name=f"ace(run)-{timestamp}",
            prompt=prompt,
            timestamp=timestamp,
            project_name=PROJECT,
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
        for artifacts_dir in iter_agent_artifact_dirs(PROJECT, newest_first=False):
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
                    payload = read_json(meta_path)
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
        return read_json(meta_path)

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
        return read_json(done_path)

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
