"""Lean waiter: parks a waiting runner near 15 MB instead of ~330 MB.

A runner blocked on its dependency wait (or a pure ``duration`` / ``until``
wait) ``exec``s this script after it has been blocked for a while. ``exec``
keeps the pid, identity token, process group, session, systemd scope,
environment, and fds 0-2, so every pid-keyed surface (WAITING visibility, kill,
hijack, holds, workspace claim) keeps working. The waiter polls the same
``ready.json`` rendezvous marker the runner did, resolves dependencies through
short-lived probe children, and ``exec``s back into the runner with an outcome:

    run_agent_runner.py --exec--> run_agent_lean_wait.py --exec--> run_agent_runner.py

Both scripts are run by path with the same interpreter and no extra interpreter
flags (never ``-I`` or ``-S``: the editable install needs ``site`` and the
inherited environment). ``ps`` shows one human-readable argv field after the
script path, such as the artifacts timestamp; the waiter ignores it.

Handoff contract (environment variables named in ``sase.env_contracts``)
------------------------------------------------------------------------

``SASE_RUNNER_LEAN_WAIT_SPEC`` is a JSON object, version 1:

``artifacts_dir``
    Absolute path of the run's artifacts directory.
``project_name``
    Project key, or ``null`` (a dependency wait with no project has no probes).
``runner_argv``
    Exactly ``[sys.executable, *sys.argv]`` of the full runner.
``mode``
    ``"dependency"`` (poll ``ready.json``, probe), ``"duration"`` or ``"until"``
    (sleep to ``deadline_epoch``).
``deadline_epoch``
    Epoch float for the time modes, ``null`` otherwise.
``heartbeat_path``
    The ``wait_checks`` heartbeat stamp (see ``wait_checks_heartbeat``) or
    ``null``, which counts as a missing heartbeat.
``bead_sync_hint``, ``bead_sync_role``
    Whether probes should also hint the beads sidecar to sync, and the role
    the runner would hint. The role is validated and carried for the contract;
    the probe derives it through ``mark_bead_wait_sync_hint``. The hint rides a
    probe (``--bead-sync-hint``) at most every 600 s from the handoff, so it
    follows the probe cadence: about every 600 s while the heartbeat is stale,
    and about every 1,800 s while it is fresh. Calling the hint in the waiter
    would load the Rust binding (+11 MB RSS per parked waiter), which is why it
    lives in the probe.
``blocked_since``, ``handed_off_at``
    Epoch floats: when the runner began blocking, and when it handed off.
``probe_interval_s`` (60), ``healthy_probe_interval_s`` (1800),
``heartbeat_fresh_s`` (300), ``probe_timeout_s`` (300)
    Optional, so tests can shrink them.

``SASE_RUNNER_LEAN_WAIT_RESULT`` is the JSON object the waiter hands back:

``outcome``
    ``"released"`` or ``"killed"``.
``artifacts_dir``
    Echo of the spec's path.
``release_source``
    ``"ready_json"``, ``"manual"`` (an unwait), ``"runner_fallback"`` (a probe
    released it), ``"timer"``, or ``null`` for a kill.
``dependencies_satisfied_at``, ``released_at``, ``killed_at``
    Epoch floats or ``null``. ``released_at`` is the dependency-release
    instant and is set only for dependency-mode releases, matching the
    in-process barrier, which stamps no release instant for pure time waits.

The return exec removes the spec, sets the result and
``SASE_RUNNER_CODE_REFRESHED=1`` (so pass 2 runs as a refreshed pass), and
execs ``runner_argv``. SIGTERM is blocked across every ``exec`` so a kill that
lands during a hop stays pending instead of killing the process uncleaned; the
program that is exec'd installs its handler and only then unblocks. If the
return exec fails the waiter unblocks, logs, retries 3 times at 5 s intervals,
then exits 1.

Import firewall
---------------

This module may import only the standard library plus
``sase.axe.run_agent_wait_ready`` and ``sase.env_contracts``. Never import
``sase.config``, ``sase.core.wait_dependency_*``, the Rust binding, telemetry,
or ``gc`` tuning, and never start a thread: that is the whole memory budget.
Dependency resolution and the beads sync hint run in the probe child
(``run_agent_wait_probe.py``) so their import cost is paid and returned per run.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
import math
import os
import random
import signal
import subprocess
import sys
import time
from typing import TYPE_CHECKING, Any

from sase.axe.run_agent_wait_ready import read_ready_result
from sase.env_contracts import (
    SASE_RUNNER_CODE_REFRESHED_ENV,
    SASE_RUNNER_LEAN_WAIT_RESULT_ENV,
    SASE_RUNNER_LEAN_WAIT_SPEC_ENV,
)

if TYPE_CHECKING:
    from types import FrameType

LEAN_WAIT_SPEC_VERSION = 1
LEAN_WAIT_MODES = ("dependency", "duration", "until")

#: Exit status for an invalid handoff spec (EX_SOFTWARE): the runner validates
#: before it execs, so an invalid spec is a programming error.
EXIT_INVALID_SPEC = 70

POLL_INTERVAL_SECONDS = 0.5
DEFAULT_PROBE_INTERVAL_SECONDS = 60.0
DEFAULT_HEALTHY_PROBE_INTERVAL_SECONDS = 1800.0
DEFAULT_HEARTBEAT_FRESH_SECONDS = 300.0
DEFAULT_PROBE_TIMEOUT_SECONDS = 300.0
#: Probes carry the beads sync hint at most this often, the cadence the
#: in-process fallback used.
BEAD_HINT_INTERVAL_SECONDS = 600.0
PROBE_STOP_GRACE_SECONDS = 2.0
PROBE_JITTER_FRACTION = 0.10
EXEC_RETRIES = 3
EXEC_RETRY_INTERVAL_SECONDS = 5.0
#: Cap on probe stdout the waiter will read: it is one short JSON line.
_PROBE_STDOUT_LIMIT_BYTES = 65536

PROBE_SCRIPT = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "run_agent_wait_probe.py"
)


@dataclass(frozen=True)
class _LeanWaitSpec:
    """Validated ``SASE_RUNNER_LEAN_WAIT_SPEC`` handoff."""

    artifacts_dir: str
    project_name: str | None
    runner_argv: tuple[str, ...]
    mode: str
    deadline_epoch: float | None
    heartbeat_path: str | None
    bead_sync_hint: bool
    bead_sync_role: str
    blocked_since: float
    handed_off_at: float
    probe_interval_s: float = DEFAULT_PROBE_INTERVAL_SECONDS
    healthy_probe_interval_s: float = DEFAULT_HEALTHY_PROBE_INTERVAL_SECONDS
    heartbeat_fresh_s: float = DEFAULT_HEARTBEAT_FRESH_SECONDS
    probe_timeout_s: float = DEFAULT_PROBE_TIMEOUT_SECONDS


def _number(
    raw: dict[str, Any],
    key: str,
    *,
    default: float | None = None,
    nullable: bool = False,
    positive: bool = False,
) -> float | None:
    """Read a finite number field; ``default`` fills an absent or null value."""
    value = raw.get(key)
    if value is None:
        if default is not None:
            return default
        if nullable:
            return None
        raise ValueError(f"{key} is required")
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{key} must be a number")
    number = float(value)
    if not math.isfinite(number) or (positive and number <= 0):
        raise ValueError(f"{key} must be a{' positive' if positive else ''} number")
    return number


def _required_number(raw: dict[str, Any], key: str) -> float:
    value = _number(raw, key)
    assert value is not None
    return value


def _optional_string(raw: dict[str, Any], key: str) -> str | None:
    value = raw.get(key)
    if value is None:
        return None
    if not isinstance(value, str) or not value:
        raise ValueError(f"{key} must be a non-empty string or null")
    return value


# symvision: tools/lean_wait_harness
def validate_lean_wait_spec(raw: object) -> _LeanWaitSpec:
    """Validate a decoded handoff spec; raise ``ValueError`` when it is not usable."""
    if not isinstance(raw, dict):
        raise ValueError("spec must be a JSON object")
    version = raw.get("version")
    if isinstance(version, bool) or version != LEAN_WAIT_SPEC_VERSION:
        raise ValueError(f"version must be {LEAN_WAIT_SPEC_VERSION}")
    artifacts_dir = raw.get("artifacts_dir")
    if not isinstance(artifacts_dir, str) or not os.path.isabs(artifacts_dir):
        raise ValueError("artifacts_dir must be an absolute path")
    runner_argv = raw.get("runner_argv")
    if (
        not isinstance(runner_argv, list)
        or not runner_argv
        or not all(isinstance(arg, str) for arg in runner_argv)
        or not runner_argv[0]
    ):
        raise ValueError("runner_argv must be a non-empty list of strings")
    mode = raw.get("mode")
    if mode not in LEAN_WAIT_MODES:
        raise ValueError(f"mode must be one of {', '.join(LEAN_WAIT_MODES)}")
    deadline_epoch = _number(raw, "deadline_epoch", nullable=True)
    if mode == "dependency" and deadline_epoch is not None:
        raise ValueError("deadline_epoch must be null in dependency mode")
    if mode != "dependency" and deadline_epoch is None:
        raise ValueError(f"deadline_epoch is required in {mode} mode")
    bead_sync_hint = raw.get("bead_sync_hint")
    if not isinstance(bead_sync_hint, bool):
        raise ValueError("bead_sync_hint must be a boolean")
    bead_sync_role = raw.get("bead_sync_role")
    if not isinstance(bead_sync_role, str):
        raise ValueError("bead_sync_role must be a string")
    probe_interval_s = _number(
        raw,
        "probe_interval_s",
        default=DEFAULT_PROBE_INTERVAL_SECONDS,
        positive=True,
    )
    healthy_probe_interval_s = _number(
        raw,
        "healthy_probe_interval_s",
        default=DEFAULT_HEALTHY_PROBE_INTERVAL_SECONDS,
        positive=True,
    )
    heartbeat_fresh_s = _number(
        raw,
        "heartbeat_fresh_s",
        default=DEFAULT_HEARTBEAT_FRESH_SECONDS,
        positive=True,
    )
    probe_timeout_s = _number(
        raw,
        "probe_timeout_s",
        default=DEFAULT_PROBE_TIMEOUT_SECONDS,
        positive=True,
    )
    assert probe_interval_s is not None
    assert healthy_probe_interval_s is not None
    assert heartbeat_fresh_s is not None
    assert probe_timeout_s is not None
    return _LeanWaitSpec(
        artifacts_dir=artifacts_dir,
        project_name=_optional_string(raw, "project_name"),
        runner_argv=tuple(runner_argv),
        mode=mode,
        deadline_epoch=deadline_epoch,
        heartbeat_path=_optional_string(raw, "heartbeat_path"),
        bead_sync_hint=bead_sync_hint,
        bead_sync_role=bead_sync_role,
        blocked_since=_required_number(raw, "blocked_since"),
        handed_off_at=_required_number(raw, "handed_off_at"),
        probe_interval_s=probe_interval_s,
        healthy_probe_interval_s=healthy_probe_interval_s,
        heartbeat_fresh_s=heartbeat_fresh_s,
        probe_timeout_s=probe_timeout_s,
    )


def _result(
    spec: _LeanWaitSpec,
    outcome: str,
    *,
    release_source: str | None = None,
    dependencies_satisfied_at: float | None = None,
    released_at: float | None = None,
    killed_at: float | None = None,
) -> dict[str, Any]:
    return {
        "version": LEAN_WAIT_SPEC_VERSION,
        "outcome": outcome,
        "artifacts_dir": spec.artifacts_dir,
        "release_source": release_source,
        "dependencies_satisfied_at": dependencies_satisfied_at,
        "released_at": released_at,
        "killed_at": killed_at,
    }


class _SigtermFlag:
    """SIGTERM sets a flag; the poll loop turns it into a ``killed`` result."""

    def __init__(self) -> None:
        self.killed_at: float | None = None

    def _handle(self, signum: int, frame: FrameType | None) -> None:
        if self.killed_at is None:
            self.killed_at = time.time()

    def install(self) -> None:
        """Install the handler, then unblock a SIGTERM that arrived while masked."""
        signal.signal(signal.SIGTERM, self._handle)
        signal.pthread_sigmask(signal.SIG_UNBLOCK, {signal.SIGTERM})


def _log(message: str) -> None:
    print(message, file=sys.stderr, flush=True)


def _heartbeat_is_fresh(spec: _LeanWaitSpec) -> bool:
    """Whether ``wait_checks`` stamped its heartbeat within ``heartbeat_fresh_s``."""
    if not spec.heartbeat_path:
        return False
    try:
        with open(spec.heartbeat_path, encoding="utf-8") as handle:
            stamp = float(handle.read(64).strip())
    except (OSError, ValueError):
        return False
    age = time.time() - stamp
    # A stamp from the future (clock step) must not suppress probes forever.
    return 0 <= age <= spec.heartbeat_fresh_s


def _probe_is_due(spec: _LeanWaitSpec, elapsed: float, jitter: float) -> bool:
    """Whether to start a probe *elapsed* seconds after the last one (or handoff).

    The short interval gates every probe. With a fresh heartbeat the healthy
    interval applies instead; the heartbeat is read only once the short
    interval has passed, and a heartbeat that goes stale mid-wait switches the
    waiter back to the short interval at once.
    """
    if elapsed < spec.probe_interval_s * jitter:
        return False
    if _heartbeat_is_fresh(spec):
        return elapsed >= spec.healthy_probe_interval_s * jitter
    return True


def _jitter() -> float:
    return random.uniform(1 - PROBE_JITTER_FRACTION, 1 + PROBE_JITTER_FRACTION)


class _Probe:
    """One running probe child, polled without blocking."""

    def __init__(self, spec: _LeanWaitSpec, *, bead_sync_hint: bool) -> None:
        assert spec.project_name is not None
        argv = [
            sys.executable,
            PROBE_SCRIPT,
            "--waiting-path",
            os.path.join(spec.artifacts_dir, "waiting.json"),
            "--artifacts-dir",
            spec.artifacts_dir,
            "--project-name",
            spec.project_name,
        ]
        if bead_sync_hint:
            argv.append("--bead-sync-hint")
        # The probe is a plain child, not a lean waiter: it must not see the spec.
        env = {
            key: value
            for key, value in os.environ.items()
            if key != SASE_RUNNER_LEAN_WAIT_SPEC_ENV
        }
        self._timeout = spec.probe_timeout_s
        self._started = time.monotonic()
        # stderr is inherited so the probe's diagnostics reach the runner output.
        self._proc = subprocess.Popen(
            argv,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            env=env,
        )
        assert self._proc.stdout is not None
        # A probe's own children may inherit the pipe and outlive it, so reads
        # after exit must never block the poll loop.
        os.set_blocking(self._proc.stdout.fileno(), False)

    def poll(self) -> tuple[bool, float | None] | None:
        """Return ``None`` while running, else ``(released, satisfied_at)``."""
        returncode = self._proc.poll()
        if returncode is None:
            if time.monotonic() - self._started < self._timeout:
                return None
            _log(
                f"Lean waiter: dependency probe exceeded {self._timeout:.0f}s; "
                "killing it and staying parked"
            )
            self.stop()
            return False, None
        output = self._drain_stdout()
        if returncode != 0:
            _log(f"Lean waiter: dependency probe exited {returncode}; staying parked")
            return False, None
        return _parse_probe_output(output)

    def _drain_stdout(self) -> bytes:
        stdout = self._proc.stdout
        assert stdout is not None
        chunks: list[bytes] = []
        total = 0
        try:
            while total < _PROBE_STDOUT_LIMIT_BYTES:
                chunk = os.read(stdout.fileno(), 4096)
                if not chunk:
                    break
                chunks.append(chunk)
                total += len(chunk)
        except OSError:  # BlockingIOError: a leaked writer still holds the pipe.
            pass
        stdout.close()
        return b"".join(chunks)

    def stop(self) -> None:
        """SIGTERM the probe, SIGKILL after the grace, and reap it."""
        proc = self._proc
        if proc.poll() is None:
            try:
                proc.terminate()
            except OSError:
                pass
            deadline = time.monotonic() + PROBE_STOP_GRACE_SECONDS
            while proc.poll() is None and time.monotonic() < deadline:
                time.sleep(0.02)
            if proc.poll() is None:
                try:
                    proc.kill()
                except OSError:
                    pass
                proc.wait()
        if proc.stdout is not None and not proc.stdout.closed:
            proc.stdout.close()


def _parse_probe_output(output: bytes) -> tuple[bool, float | None]:
    """Parse the probe's one JSON line; anything unparseable is "not released"."""
    lines = output.decode("utf-8", errors="replace").strip().splitlines()
    try:
        payload = json.loads(lines[-1])
    except (IndexError, json.JSONDecodeError):
        _log("Lean waiter: dependency probe printed no result; staying parked")
        return False, None
    if not isinstance(payload, dict) or payload.get("released") is not True:
        return False, None
    satisfied_at = payload.get("satisfied_at")
    if isinstance(satisfied_at, bool) or not isinstance(satisfied_at, (int, float)):
        return True, None
    return True, float(satisfied_at)


def _released_result(
    spec: _LeanWaitSpec,
    source: str,
    *,
    satisfied_at: float | None = None,
) -> dict[str, Any]:
    now = time.time()
    return _result(
        spec,
        "released",
        release_source=source,
        dependencies_satisfied_at=satisfied_at,
        released_at=now if spec.mode == "dependency" else None,
    )


def _killed_result(spec: _LeanWaitSpec, sigterm: _SigtermFlag) -> dict[str, Any]:
    return _result(
        spec,
        "killed",
        killed_at=sigterm.killed_at if sigterm.killed_at is not None else time.time(),
    )


def _run_lean_wait(spec: _LeanWaitSpec, sigterm: _SigtermFlag) -> dict[str, Any]:
    """Poll until the wait is released or killed, and return the result payload."""
    ready_path = os.path.join(spec.artifacts_dir, "ready.json")
    dependency = spec.mode == "dependency"
    handoff_age = max(0.0, time.time() - spec.handed_off_at)
    probe_reference = time.monotonic() - handoff_age
    jitter = _jitter()
    next_hint_at = (
        probe_reference + BEAD_HINT_INTERVAL_SECONDS
        if dependency and spec.project_name and spec.bead_sync_hint
        else None
    )
    probe: _Probe | None = None
    try:
        while True:
            if sigterm.killed_at is not None:
                return _killed_result(spec, sigterm)
            if dependency:
                if os.path.exists(ready_path):
                    ready = read_ready_result(ready_path)
                    if ready:
                        if ready.unwait:
                            return _released_result(spec, "manual")
                        return _released_result(
                            spec,
                            "ready_json",
                            satisfied_at=ready.dependencies_satisfied_at,
                        )
            elif spec.deadline_epoch is not None and time.time() >= spec.deadline_epoch:
                return _released_result(spec, "timer")
            if dependency and spec.project_name:
                now = time.monotonic()
                if probe is None:
                    if _probe_is_due(spec, now - probe_reference, jitter):
                        include_hint = next_hint_at is not None and now >= next_hint_at
                        if include_hint:
                            next_hint_at = now + BEAD_HINT_INTERVAL_SECONDS
                        try:
                            probe = _Probe(spec, bead_sync_hint=include_hint)
                        except OSError as exc:
                            _log(f"Lean waiter: could not start probe: {exc}")
                            probe_reference = now
                            jitter = _jitter()
                else:
                    outcome = probe.poll()
                    if outcome is not None:
                        probe = None
                        probe_reference = time.monotonic()
                        jitter = _jitter()
                        released, satisfied_at = outcome
                        if released:
                            print(
                                "Dependencies satisfied by runner fallback "
                                "(ready.json not observed)",
                                flush=True,
                            )
                            return _released_result(
                                spec, "runner_fallback", satisfied_at=satisfied_at
                            )
            time.sleep(POLL_INTERVAL_SECONDS)
    finally:
        if probe is not None:
            probe.stop()


def _exec_back(
    spec: _LeanWaitSpec, result: dict[str, Any], sigterm: _SigtermFlag
) -> None:
    """``exec`` the runner with the result; return only if every attempt failed."""
    for attempt in range(1 + EXEC_RETRIES):
        env = dict(os.environ)
        env.pop(SASE_RUNNER_LEAN_WAIT_SPEC_ENV, None)
        env[SASE_RUNNER_LEAN_WAIT_RESULT_ENV] = json.dumps(result)
        env[SASE_RUNNER_CODE_REFRESHED_ENV] = "1"
        sys.stdout.flush()
        sys.stderr.flush()
        # A kill that lands during the hop stays pending until the exec'd
        # program installs its handler and unblocks.
        signal.pthread_sigmask(signal.SIG_BLOCK, {signal.SIGTERM})
        try:
            os.execve(spec.runner_argv[0], list(spec.runner_argv), env)
        except (OSError, ValueError) as exc:
            signal.pthread_sigmask(signal.SIG_UNBLOCK, {signal.SIGTERM})
            _log(
                f"Lean waiter: failed to exec runner ({exc}); "
                f"attempt {attempt + 1} of {1 + EXEC_RETRIES}"
            )
        if attempt == EXEC_RETRIES:
            return
        deadline = time.monotonic() + EXEC_RETRY_INTERVAL_SECONDS
        while time.monotonic() < deadline:
            if sigterm.killed_at is not None and result["outcome"] != "killed":
                # The kill arrived while the runner could not be reached: let
                # pass 2 take its kill path instead of finishing the wait.
                result = _killed_result(spec, sigterm)
                break
            time.sleep(
                max(0.0, min(POLL_INTERVAL_SECONDS, deadline - time.monotonic()))
            )


def main() -> int:
    """Entry point; argv holds only a human-readable ``ps`` label, so it is ignored."""
    raw = os.environ.get(SASE_RUNNER_LEAN_WAIT_SPEC_ENV)
    try:
        if raw is None:
            raise ValueError(f"{SASE_RUNNER_LEAN_WAIT_SPEC_ENV} is not set")
        spec = validate_lean_wait_spec(json.loads(raw))
    except ValueError as exc:
        _log(f"run_agent_lean_wait: invalid handoff spec: {exc}")
        return EXIT_INVALID_SPEC
    sigterm = _SigtermFlag()
    sigterm.install()
    print(f"Parked in lean waiter (pid {os.getpid()}, mode {spec.mode})", flush=True)
    result = _run_lean_wait(spec, sigterm)
    print(
        f"Lean waiter returning to runner (outcome={result['outcome']}, "
        f"source={result['release_source']})",
        flush=True,
    )
    _exec_back(spec, result, sigterm)
    return 1


if __name__ == "__main__":
    sys.exit(main())
