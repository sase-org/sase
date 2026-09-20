"""Shared fixture plumbing for the ToolRun black-box harness and its pytest twin.

Every helper drives the real ``sase`` executable and the real Rust-backed store. The
only fault injection is at the filesystem/process boundary; nothing here substitutes
a fake store or a mocked ``Popen``.
"""

from __future__ import annotations

import json
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent.parent
RUN_SILENT = ROOT / "tools" / "run_silent"
HELPER = Path(__file__).resolve().with_name("_smoke_tool_runs_helper.py")
PASS = "pass"
FAIL = "fail"
NOT_RUN = "not-run"
RUN_LINE_PREFIX = "sase tool run "


def sase_interpreter(sase: str) -> str:
    """Return the Python interpreter behind a ``sase`` console script."""

    try:
        first = Path(sase).read_text(encoding="utf-8", errors="replace").splitlines()[0]
    except (OSError, IndexError):
        return sys.executable
    if first.startswith("#!"):
        parts = first[2:].split()
        if parts and Path(parts[0]).exists():
            return parts[0]
    return sys.executable


def case(
    case_id: str,
    ok: bool,
    *,
    dod: Sequence[str] = (),
    run_ids: Sequence[str] = (),
    **observed: Any,
) -> dict[str, Any]:
    """Build one harness case result."""

    return {
        "id": case_id,
        "status": PASS if ok else FAIL,
        "dod": list(dod),
        "run_ids": [item for item in run_ids if item],
        "observed": observed,
    }


def not_run(case_id: str, reason: str, *, dod: Sequence[str] = ()) -> dict[str, Any]:
    return {
        "id": case_id,
        "status": NOT_RUN,
        "dod": list(dod),
        "run_ids": [],
        "observed": {"reason": reason},
    }


@dataclass
class Harness:
    """One isolated ToolRun world: temp dir, private HOME, and a default store."""

    sase: str
    live: bool
    keep: bool
    tmp: Path
    python: str
    base_env: dict[str, str]
    children: list[subprocess.Popen[str]] = field(default_factory=list)
    run_log: list[dict[str, str]] = field(default_factory=list)
    snapshots: dict[str, Any] = field(default_factory=dict)
    _fixture_project: Path | None = None
    _counter: int = 0

    @classmethod
    def create(cls, *, sase: str, live: bool, keep: bool) -> Harness:
        tmp = Path(tempfile.mkdtemp(prefix="sase-tool-runs-harness-"))
        user_home = tmp / "user-home"
        user_home.mkdir()
        # A black-box child is a real sase process: neither the caller's SASE_* identity
        # nor pytest's own markers (which arm sandbox guards) may leak into it.
        env = {
            k: v
            for k, v in os.environ.items()
            if not k.startswith(("SASE_", "PYTEST_"))
        }
        # A private HOME keeps the caller's ~/.config/sase and plugin overlays out of
        # every child; the caller's real home directory is never read or written.
        env["HOME"] = str(user_home)
        env["GIT_CEILING_DIRECTORIES"] = str(tmp)
        env["GIT_CONFIG_GLOBAL"] = os.devnull
        env["GIT_CONFIG_NOSYSTEM"] = "1"
        for key in ("XDG_CONFIG_HOME", "XDG_STATE_HOME", "XDG_DATA_HOME"):
            env.pop(key, None)
        env["SASE_HOME"] = str(tmp / "sase-home")
        (tmp / "sase-home").mkdir()
        return cls(
            sase=sase,
            live=live,
            keep=keep,
            tmp=tmp,
            python=sase_interpreter(sase),
            base_env=env,
        )

    # -- environments and processes -------------------------------------------------

    def env(self, home: Path | None = None, **extra: str | None) -> dict[str, str]:
        env = dict(self.base_env)
        if home is not None:
            env["SASE_HOME"] = str(home)
        for key, value in extra.items():
            if value is None:
                env.pop(key, None)
            else:
                env[key] = value
        return env

    @property
    def home(self) -> Path:
        return Path(self.base_env["SASE_HOME"])

    def world(self, name: str, *, user_config: str | None = None) -> dict[str, str]:
        """An environment with its own SASE_HOME and private HOME (own user config)."""

        root = self.tmp / f"world-{name}"
        (root / "sase-home").mkdir(parents=True)
        (root / "user-home").mkdir()
        if user_config is not None:
            config = root / "user-home" / ".config" / "sase"
            config.mkdir(parents=True)
            (config / "sase.yml").write_text(user_config, encoding="utf-8")
        return self.env(root / "sase-home", HOME=str(root / "user-home"))

    def run(
        self,
        args: Sequence[str],
        *,
        env: dict[str, str] | None = None,
        cwd: Path | None = None,
        timeout: float = 120.0,
        preexec: Callable[[], None] | None = None,
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [self.sase, *args],
            check=False,
            capture_output=True,
            text=True,
            errors="replace",
            env=env if env is not None else self.env(),
            cwd=str(cwd) if cwd is not None else str(self.project()),
            timeout=timeout,
            preexec_fn=preexec,
        )

    def spawn(
        self,
        args: Sequence[str],
        *,
        env: dict[str, str] | None = None,
        cwd: Path | None = None,
    ) -> subprocess.Popen[str]:
        proc = subprocess.Popen(
            [self.sase, *args],
            env=env if env is not None else self.env(),
            cwd=str(cwd) if cwd is not None else str(self.project()),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            start_new_session=True,
        )
        self.children.append(proc)
        return proc

    def python_run(
        self, args: Sequence[str], *, env: dict[str, str] | None = None
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [self.python, *args],
            check=False,
            capture_output=True,
            text=True,
            env=env if env is not None else self.env(),
            cwd=str(self.tmp),
            timeout=120,
        )

    def helper(
        self,
        command: str,
        payload: dict[str, Any] | None = None,
        *,
        env: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        """Run one in-process helper command under the sase interpreter."""

        proc = self.python_run(
            [str(HELPER), command, json.dumps(payload or {})], env=env
        )
        if proc.returncode != 0:
            raise RuntimeError(f"helper {command} failed: {proc.stderr[-800:]}")
        return json.loads(proc.stdout)  # type: ignore[no-any-return]

    # -- queries --------------------------------------------------------------------

    def show(self, run_id: str, *, env: dict[str, str] | None = None) -> dict[str, Any]:
        proc = self.run(["tool", "show", run_id, "-j"], env=env, cwd=self.tmp)
        return json.loads(proc.stdout) if proc.returncode == 0 else {}

    def runs(
        self,
        *extra: str,
        env: dict[str, str] | None = None,
        cwd: Path | None = None,
    ) -> list[dict[str, Any]]:
        proc = self.run(
            ["tool", "runs", "-j", "-a", "-n", "100", *extra],
            env=env,
            cwd=cwd or self.tmp,
        )
        try:
            return list(json.loads(proc.stdout).get("runs") or ())
        except json.JSONDecodeError:
            return []

    def note(
        self, run_id: str, purpose: str, *, owner: str = "none", kind: str = "fixture"
    ) -> None:
        if run_id:
            self.run_log.append(
                {
                    "run_id": run_id,
                    "fixture_or_live": kind,
                    "owner": owner,
                    "purpose": purpose,
                }
            )

    # -- fixtures -------------------------------------------------------------------

    def unique(self, prefix: str) -> str:
        self._counter += 1
        return f"{prefix}-{self._counter}"

    def project(self) -> Path:
        """The standard fixture project: a temp git repo with a known catalog."""

        if self._fixture_project is None:
            self._fixture_project = self.make_project(
                "fixture-project", standard_catalog(), standard_files()
            )
        return self._fixture_project

    def make_project(
        self,
        name: str,
        catalog: dict[str, Any],
        files: dict[str, str] | None = None,
        *,
        extra: dict[str, Any] | None = None,
    ) -> Path:
        root = self.tmp / name
        (root / "sase").mkdir(parents=True)
        config: dict[str, Any] = {"tools": catalog, **(extra or {})}
        (root / "sase" / "sase.yml").write_text(
            json.dumps(config, indent=2), encoding="utf-8"
        )
        for relative, text in (files or {}).items():
            target = root / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(text, encoding="utf-8")
        self.git(root, "init", "-q")
        self.git(root, "config", "user.email", "harness@example.invalid")
        self.git(root, "config", "user.name", "harness")
        self.git(root, "add", "-A")
        self.git(root, "commit", "-qm", "fixture")
        return root

    def git(self, root: Path, *args: str) -> None:
        subprocess.run(
            ["git", *args], cwd=root, check=True, capture_output=True, env=self.env()
        )

    # -- cleanup --------------------------------------------------------------------

    def cleanup(self) -> None:
        for proc in self.children:
            kill_tree(proc)
        subprocess.run(
            ["chmod", "-R", "u+rwX", str(self.tmp)], check=False, capture_output=True
        )
        if not self.keep:
            shutil.rmtree(self.tmp, ignore_errors=True)


def kill_tree(proc: subprocess.Popen[Any]) -> None:
    if proc.poll() is not None:
        return
    try:
        os.killpg(proc.pid, signal.SIGKILL)
    except OSError:
        try:
            proc.kill()
        except OSError:
            pass
    try:
        proc.wait(timeout=2)
    except Exception:  # noqa: BLE001 - harness cleanup must not raise.
        pass


_SNAPSHOT_RUN_FIELDS = (
    "schema_version",
    "run_id",
    "tool_name",
    "source",
    "executor",
    "state",
    "exit_code",
    "signal",
    "duration_ms",
    "owner_kind",
    "owner_id",
    "parent_run_id",
    "definition_digest",
    "lost_reason",
    "mutated_input",
    "evidence_completeness",
)


def redact_run(run: dict[str, Any]) -> dict[str, Any]:
    """A query snapshot safe to publish: no argv, paths, pids, or environment."""

    logs = run.get("logs") or {}
    redacted = {key: run.get(key) for key in _SNAPSHOT_RUN_FIELDS if key in run}
    redacted["logs"] = {
        "stdout": bool(logs.get("stdout_path")),
        "stderr": bool(logs.get("stderr_path")),
        "events": bool(logs.get("events_path")),
    }
    return redacted


def redact_show(shown: dict[str, Any]) -> dict[str, Any]:
    """Redact a ``tool show -j`` envelope to identities, states, and counts."""

    return {
        "schema_version": shown.get("schema_version"),
        "run": redact_run(shown.get("run") or {}),
        "stages": [
            {
                key: stage.get(key)
                for key in ("description", "elapsed_ms", "exit_code", "incomplete")
            }
            for stage in shown.get("stages") or ()
        ],
        "sample_count": len(shown.get("samples") or ()),
        "unattributed_ms": shown.get("unattributed_ms"),
        "output_truncation": shown.get("output_truncation"),
    }


def run_id_from(stderr: str) -> str:
    """The durable id from the wrapper's ``sase tool run <id>`` header line."""

    for line in stderr.splitlines():
        if line.startswith(RUN_LINE_PREFIX):
            return line.split()[-1]
    return ""


def wait_for(
    predicate: Callable[[], bool], timeout: float = 20.0, step: float = 0.05
) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(step)
    return False


def group_alive(pgid: object) -> bool:
    if type(pgid) is not int or pgid <= 0:
        return False
    try:
        os.killpg(pgid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def standard_catalog() -> dict[str, Any]:
    python = sys.executable
    return {
        "check": {
            "argv": ["bash", "check.sh"],
            "description": "Fixture staged check.",
            "stages": "run_silent",
            "inputs": ["inputs/*.txt"],
            "env": ["FIXTURE_FLAG"],
            "args": "deny",
            "fingerprint": {"toolchain": {"python": [python, "--version"]}},
        },
        "quick": {
            "argv": [python, "-c", "print('q')"],
            "description": "Fixture quick command.",
            "args": "allow",
        },
        "test": {
            "argv": [python, "fake_test.py"],
            "description": "Fixture failing test runner.",
            "stages": "none",
            "args": "allow",
        },
    }


def standard_files() -> dict[str, str]:
    return {
        "check.sh": (
            "set -u\n"
            f"RS={json.dumps(str(RUN_SILENT))}\n"
            '"$RS" alpha true || exit $?\n'
            '"$RS" alpha true || exit $?\n'
            "\"$RS\" beta sh -c 'sleep 0.2; exit 3' || exit $?\n"
            '"$RS" gamma true\n'
        ),
        "fake_test.py": (
            "import sys\n"
            "lines = open(sys.argv[1]).read().splitlines() if len(sys.argv) > 1 else []\n"
            "for line in lines:\n"
            "    print(line)\n"
            "sys.exit(1 if any(x.startswith('FAIL') for x in lines) else 0)\n"
        ),
        "failing.txt": "".join(f"case {i}\n" for i in range(1, 31)) + "FAIL: boom\n",
        "inputs/a.txt": "input a\n",
    }
