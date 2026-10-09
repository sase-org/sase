#!/usr/bin/env python3
"""Execution pipeline for the ``sase_install`` engine (stdlib-only).

This module is the live half of the installer: the log file, the code-swap
writer lock, the pre-swap backup (with its restore command), the ``uv tool
install`` swap, post-swap verification, the scheduler restart, and the final
summary. It never imports ``sase``: every parity-sensitive shape (the lock
path, the holder payload, the swap argv, the overrides content) is mirrored
here as plain functions, and parity is enforced by tests that *may* import
``sase``.

Subprocess execution goes through the injectable :class:`Runner` seam so the
hermetic tests can drive the whole pipeline with fake ``uv``/``sase``
executables (or none at all). Wall-clock waits (the lock retry) go through an
injectable ``sleep`` for the same reason.
"""

from __future__ import annotations

import fcntl
import json
import os
import shlex
import shutil
import subprocess
import sys
import tempfile
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import TextIO

import _sase_core_source_identity as core_identity
import _sase_install_core as install_core
import _sase_install_env as install_env
import _sase_install_plan as install_plan
import _sase_install_state as install_state
import _sase_install_ui as install_ui


#: Filename of the code-swap writer lock (mirrors
#: ``sase.dev_update.code_swap_lock.CODE_SWAP_LOCK_FILENAME``).
LOCK_FILENAME = "code-swap-v2.lock"

#: How long the pipeline waits for the code-swap lock before giving up.
LOCK_TIMEOUT_SECONDS = 120.0

#: Poll interval while waiting for the code-swap lock.
LOCK_POLL_SECONDS = 0.5

#: Timeout for the ``uv tool install`` swap itself.
SWAP_TIMEOUT_SECONDS = 600.0

#: Timeout for the post-install ``sase update -n -j`` agreement probe.
UPDATE_AGREE_TIMEOUT_SECONDS = 120.0

#: Timeout for the remaining post-install probes (imports, health, version).
VERIFY_TIMEOUT_SECONDS = 60.0

#: Timeout for the scheduler restart.
RESTART_TIMEOUT_SECONDS = 120.0

#: Timeout for the repeat-run ``sase core health`` probe.
HEALTH_TIMEOUT_SECONDS = 60.0

#: Timeout for the dev re-apply step (``just rust-dev-install-uv-tool``).
#: Mirrors ``sase.dev_update.command.DEV_UPDATE_BUILD_COMMAND_TIMEOUT_SECONDS``
#: without importing ``sase``.
REAPPLY_TIMEOUT_SECONDS = 3600.0

#: ``SASE_RUST_DEV_PROFILE`` value for the re-apply rebuild (the same
#: dev-update Cargo profile ``sase update --to dev`` uses).
REAPPLY_RUST_PROFILE = "dev-update"

#: Timeout for the prepare-stage ``git clone`` of a missing core checkout.
PREPARE_CLONE_TIMEOUT_SECONDS = 300.0

#: Timeout for the prepare-stage core fast-forward merge.
PREPARE_FF_TIMEOUT_SECONDS = 120.0

#: Timeout for best-effort ``git rev-parse`` calls behind summary SHAs.
SUMMARY_GIT_TIMEOUT_SECONDS = 30.0

#: Length of the SHAs named in dev summaries (matches the design contract).
SUMMARY_SHORT_LENGTH = 7

#: ``uv`` reinstall flag position: ``--python`` is inserted after this token.
_REINSTALL_TOKEN = "--reinstall"

#: Timestamps in log/backup filenames (UTC, filesystem-safe).
_STAMP_FORMAT = "%Y%m%dT%H%M%SZ"


@dataclass(frozen=True)
class RunnerResult:
    """The outcome of one subprocess invocation through the runner seam."""

    returncode: int
    stdout: str = ""
    stderr: str = ""
    timed_out: bool = False


#: A command runner: ``(argv, *, timeout, cwd, env) -> RunnerResult``.
Runner = Callable[..., RunnerResult]


@dataclass
class SwapLock:
    """A held code-swap writer lock (release with :meth:`release`)."""

    fd: int
    path: Path
    _released: bool = field(default=False, repr=False)

    def release(self) -> None:
        """Clear the holder payload, unlock, and close the lock file."""
        if self._released:
            return
        self._released = True
        try:
            os.lseek(self.fd, 0, os.SEEK_SET)
            os.ftruncate(self.fd, 0)
        except OSError:
            pass
        try:
            fcntl.flock(self.fd, fcntl.LOCK_UN)
        except OSError:
            pass
        try:
            os.close(self.fd)
        except OSError:
            pass

    def __enter__(self) -> SwapLock:
        return self

    def __exit__(self, *exc: object) -> None:
        self.release()


def lock_path_for(sase_home: str | Path) -> Path:
    """Return the code-swap lock path (mirrors ``sase``'s lock location)."""
    return Path(sase_home) / "locks" / LOCK_FILENAME


def holders_dir_for(sase_home: str | Path) -> Path:
    """Return the reader/advisory holder directory (mirrors ``sase``)."""
    return Path(sase_home) / "locks" / "code-swap.holders"


def log_path_for(
    sase_home: str | Path,
    *,
    now: datetime | None = None,
    pid: int | None = None,
) -> Path:
    """Return the per-run log path for this install invocation."""
    stamp = (now or datetime.now(UTC)).strftime(_STAMP_FORMAT)
    return (
        Path(sase_home)
        / "logs"
        / "install"
        / f"install-{stamp}-{pid or os.getpid()}.log"
    )


def backup_path_for(sase_home: str | Path) -> Path:
    """Return the pre-swap backup path (mirrors the engine contract)."""
    return Path(sase_home) / "install" / "last-install.json"


def _display_op(op: str) -> str:
    """Mirror ``sase``'s holder op display names, plus the installer ops."""
    return {
        "bead.work": "sase bead work",
        "dev.update": "sase dev update",
        "agent.runner": "agent runner",
        "install.pypi": "just install",
        "install.dev": "just install-dev",
    }.get(op, op)


def format_holder(holder: Mapping[str, object]) -> str:
    """Format a lock holder payload the way ``sase`` formats it."""
    op = _display_op(str(holder.get("op") or "sase process"))
    pid = holder.get("pid", "unknown")
    command = holder.get("command")
    started = holder.get("started_at")
    pieces = [f"{op} (pid {pid})"]
    if isinstance(command, list) and command:
        pieces.append(f"running `{' '.join(str(part) for part in command)}`")
    if isinstance(started, str) and started:
        pieces.append(f"started {started}")
    return "; ".join(pieces)


def read_writer_holder(lock_path: str | Path) -> dict[str, object] | None:
    """Return the writer holder payload recorded in *lock_path*, if any."""
    try:
        raw = Path(lock_path).read_text(encoding="utf-8").strip()
        value = json.loads(raw) if raw else None
    except (OSError, ValueError):
        return None
    return value if isinstance(value, dict) else None


def describe_blocker(lock_path: str | Path) -> str:
    """Return a human description of whoever holds the writer lock."""
    holder = read_writer_holder(lock_path)
    if holder is None:
        return "the active source-tree swap did not record its identity"
    return format_holder(holder)


def is_process_running(pid: int) -> bool:
    """Return whether *pid* names a live, non-zombie process (stdlib-only).

    Mirrors ``sase.ace.hooks.processes.is_process_running`` without importing
    it: signal 0 probes existence, and a Linux ``/proc`` status read filters
    zombies, which answer the signal but are effectively dead.
    """
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    if sys.platform.startswith("linux"):
        try:
            with open(f"/proc/{pid}/stat", encoding="utf-8") as handle:
                fields = handle.read().rsplit(")", 1)
        except OSError:
            return False
        if len(fields) == 2:
            state = fields[1].split()
            if len(state) >= 1 and state[0] == "Z":
                return False
    return True


def count_live_advisory_runners(sase_home: str | Path) -> int:
    """Count live advisory (agent-runner) holders without blocking the swap.

    Dead holder files are removed best-effort, mirroring ``sase``'s reaping.
    Advisory holders never block a swap; a non-zero count becomes a ``⚠`` row.
    """
    holders_dir = holders_dir_for(sase_home)
    try:
        paths = tuple(holders_dir.glob("*.advisory.json"))
    except OSError:
        return 0
    live = 0
    for path in paths:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if not isinstance(payload, dict):
            continue
        try:
            pid = int(payload.get("pid", 0))
        except (TypeError, ValueError):
            continue
        if pid > 0 and is_process_running(pid):
            live += 1
        else:
            try:
                path.unlink()
            except OSError:
                pass
    return live


def _holder_payload(op: str, command: Sequence[str]) -> dict[str, object]:
    """Build the writer holder payload (mirrors ``sase``'s holder shape)."""
    return {
        "pid": os.getpid(),
        "op": op,
        "command": [str(part) for part in command],
        "started_at": datetime.now(UTC).isoformat(),
        "blocking": True,
    }


def _write_holder(fd: int, holder: Mapping[str, object]) -> None:
    data = json.dumps(dict(holder), sort_keys=True).encode("utf-8")
    os.lseek(fd, 0, os.SEEK_SET)
    os.ftruncate(fd, 0)
    os.write(fd, data)


def acquire_swap_lock(
    lock_path: str | Path,
    *,
    op: str,
    command: Sequence[str] = (),
    timeout: float = LOCK_TIMEOUT_SECONDS,
    poll_interval: float = LOCK_POLL_SECONDS,
    disabled: bool = False,
    sleep: Callable[[float], None] = time.sleep,
    on_wait: Callable[[str, float], None] | None = None,
) -> tuple[SwapLock | None, str | None]:
    """Take the code-swap writer lock, retrying for up to *timeout* seconds.

    Returns ``(lock, None)`` on success, or ``(None, holder_text)`` when the
    lock stayed busy. *on_wait* is called with the current holder description
    and elapsed seconds on every poll so the progress renderer can show who
    is being waited on. Honors the ``SASE_DISABLE_CODE_SWAP_LOCK=1`` escape
    hatch through *disabled*.
    """
    path = Path(lock_path)
    if disabled:
        return SwapLock(fd=-1, path=path, _released=True), None
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
    except OSError:
        pass
    fd = os.open(path, os.O_RDWR | os.O_CREAT, 0o666)
    start = time.monotonic()
    try:
        while True:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                elapsed = time.monotonic() - start
                if elapsed >= timeout:
                    return None, describe_blocker(path)
                if on_wait is not None:
                    on_wait(describe_blocker(path), elapsed)
                sleep(poll_interval)
                continue
            except OSError:
                os.close(fd)
                raise
            _write_holder(fd, _holder_payload(op, command))
            return SwapLock(fd=fd, path=path), None
    except BaseException:
        try:
            os.close(fd)
        except OSError:
            pass
        raise


def default_runner(
    argv: Sequence[str | Path],
    *,
    timeout: float,
    cwd: str | Path | None = None,
    env: Mapping[str, str] | None = None,
) -> RunnerResult:
    """Run *argv* with *timeout*, capturing both streams (the real seam)."""
    try:
        completed = subprocess.run(
            [str(part) for part in argv],
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout,
            stdin=subprocess.DEVNULL,
            cwd=None if cwd is None else str(cwd),
            env=None if env is None else dict(env),
        )
    except subprocess.TimeoutExpired as exc:
        out = (
            exc.stdout.decode() if isinstance(exc.stdout, bytes) else (exc.stdout or "")
        )
        err = (
            exc.stderr.decode() if isinstance(exc.stderr, bytes) else (exc.stderr or "")
        )
        return RunnerResult(returncode=124, stdout=out, stderr=err, timed_out=True)
    except OSError as exc:
        return RunnerResult(returncode=127, stdout="", stderr=str(exc))
    return RunnerResult(
        returncode=completed.returncode,
        stdout=completed.stdout,
        stderr=completed.stderr,
    )


def scrubbed_env(env: Mapping[str, str]) -> dict[str, str]:
    """Return *env* without the interpreter selectors verification scrubs."""
    return {
        key: value
        for key, value in env.items()
        if key not in ("PYTHONPATH", "PYTHONHOME", "VIRTUAL_ENV")
    }


def tool_python_for(tool_dir: str | Path) -> Path:
    """Return the tool environment's own interpreter path."""
    return Path(tool_dir) / "bin" / "python"


def managed_sase_exe(*, tool_dir: str | Path, bin_dir: str | Path | None) -> Path:
    """Return the managed ``sase`` executable for verification and restart.

    ``bin_dir`` is the entry point's resolved binary location: a directory
    holding ``sase`` in tests and hermetic layouts, or the ``sase`` executable
    itself when it came from ``uv tool dir --bin``. The tool venv's own
    ``bin/sase`` is the final fallback.
    """
    if bin_dir is not None:
        candidate = Path(bin_dir)
        if candidate.is_dir():
            nested = candidate / "sase"
            if nested.exists():
                return nested
        elif candidate.exists():
            return candidate
    return Path(tool_dir) / "bin" / "sase"


def swap_argv_for(
    plan: install_plan.InstallPlan,
    *,
    tool_python: str | Path | None = None,
    env_exists: bool = False,
) -> list[str]:
    """Return the swap argv, pinning the interpreter exactly when needed.

    ``uv tool install --force --reinstall`` recreates the tool environment
    with uv's default interpreter instead of keeping the existing one
    (measured: a 3.13 env came back as 3.14.7), so an existing environment
    keeps its own interpreter through ``--python`` unless the user asked with
    ``--python`` (which the plan already carries). Fresh environments take
    uv's default.
    """
    argv = list(plan.swap_argv)
    requested: str | None = None
    if plan.python.requested and plan.python.target:
        requested = plan.python.target
    elif env_exists and not plan.python.requested and tool_python is not None:
        requested = str(tool_python)
    if requested is None:
        return argv
    try:
        anchor = argv.index(_REINSTALL_TOKEN) + 1
    except ValueError:
        anchor = len(argv)
    return [*argv[:anchor], "--python", requested, *argv[anchor:]]


@dataclass
class BackupInfo:
    """The pre-swap backup: where it lives and how to restore by hand."""

    path: Path
    restore_argv: list[str]
    restore_command: str
    previous_core_editable: bool


def _requirement_snapshot(
    req: install_state.InstallRequirement,
) -> dict[str, object]:
    return {
        "name": req.name,
        "extras": list(req.extras),
        "specifier": req.specifier,
        "editable": req.editable,
        "git": req.git,
        "git_ref": req.git_ref,
        "url": req.url,
    }


def write_backup(
    backup_path: str | Path,
    *,
    state: install_state.InstallState,
    env: Mapping[str, str] | None = None,
) -> BackupInfo:
    """Write the pre-swap backup and return the hand-restore command.

    The backup holds the previous receipt requirements plus a restore argv
    built with the parity ``build_reinstall_set`` shape (``--overrides`` when
    the *previous* set was editable). When the previous core was editable the
    command names the follow-up ``just rust-dev-install-uv-tool`` rebuild.
    Nothing here rolls anything back; the command is printed on failure so a
    human can restore deliberately.
    """
    path = Path(backup_path)
    previous: list[install_state.InstallRequirement] = []
    if state.receipt is not None:
        previous = [state.receipt.primary, *state.receipt.plugins]
    overrides = install_plan.editable_override_lines(previous)
    overrides_arg = str(install_env.editable_overrides_path(env)) if overrides else None
    restore_argv = install_plan.build_swap_argv(
        previous[0] if previous else install_state.InstallRequirement(name="sase"),
        previous[1:] if previous else (),
        overrides=overrides_arg,
    )
    core_dist = state.find_dist(install_plan.CORE_DIST_NAME)
    core_editable = bool(core_dist is not None and core_dist.editable_path)
    restore_command = " ".join(shlex.quote(part) for part in restore_argv)
    if core_editable:
        restore_command += " && just rust-dev-install-uv-tool"
    payload = {
        "schema_version": 1,
        "written_at": datetime.now(UTC).isoformat(),
        "previous_requirements": [_requirement_snapshot(req) for req in previous],
        "restore_argv": restore_argv,
        "restore_command": restore_command,
        "previous_core_editable": core_editable,
    }
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    except OSError:
        pass
    return BackupInfo(
        path=path,
        restore_argv=restore_argv,
        restore_command=restore_command,
        previous_core_editable=core_editable,
    )


@dataclass(frozen=True)
class VerifyCheck:
    """One post-swap verification outcome."""

    name: str
    ok: bool
    detail: str = ""
    warning_only: bool = False


def _parse_json_object(text: str) -> dict[str, object] | None:
    try:
        value = json.loads(text)
    except ValueError:
        return None
    return value if isinstance(value, dict) else None


def verify_pypi_install(
    *,
    plan: install_plan.InstallPlan,
    state: install_state.InstallState,
    tool_dir: str | Path,
    sase_exe: str | Path,
    tool_python: str | Path,
    env: Mapping[str, str],
    run: Callable[..., RunnerResult],
    update_timeout: float = UPDATE_AGREE_TIMEOUT_SECONDS,
    verify_timeout: float = VERIFY_TIMEOUT_SECONDS,
) -> list[VerifyCheck]:
    """Verify a PyPI swap from a neutral cwd with a scrubbed environment.

    Every probe runs the tool environment's own executables with
    ``PYTHONPATH``/``PYTHONHOME``/``VIRTUAL_ENV`` removed so an activated
    checkout ``.venv`` can neither shadow the install nor fake a pass.
    """
    checks: list[VerifyCheck] = []
    clean = scrubbed_env(env)
    tmp = Path(tempfile.mkdtemp(prefix="sase-install-verify-"))
    site_packages = install_state.find_site_packages(tool_dir)
    site_root = str(site_packages) if site_packages is not None else ""
    host_version = next(
        (row.target.version for row in plan.rows if row.role == "host"), None
    )

    import_probe = (
        "import json,sys;"
        "name=sys.argv[1];"
        "mod=__import__(name);"
        "print(json.dumps(getattr(mod,'__file__','')))"
    )
    locations: dict[str, str] = {}
    imports_ok = True
    for module in ("sase", "sase_core_rs"):
        result = run(
            [str(tool_python), "-I", "-c", import_probe, module],
            timeout=verify_timeout,
            cwd=tmp,
            env=clean,
        )
        location = ""
        if result.returncode == 0:
            try:
                location = str(json.loads(result.stdout.strip() or '""'))
            except ValueError:
                location = ""
        locations[module] = location
        if not location or (site_root and not location.startswith(site_root)):
            imports_ok = False
    if imports_ok:
        checks.append(
            VerifyCheck(
                name="imports",
                ok=True,
                detail="sase and sase_core_rs import from the tool environment",
            )
        )
    else:
        checks.append(
            VerifyCheck(
                name="imports",
                ok=False,
                detail=f"sase -> {locations['sase'] or 'missing'}; "
                f"sase_core_rs -> {locations['sase_core_rs'] or 'missing'}",
            )
        )

    health = run(
        [str(sase_exe), "core", "health", "-j"],
        timeout=verify_timeout,
        cwd=tmp,
        env=clean,
    )
    health_doc = _parse_json_object(health.stdout) if health.returncode == 0 else None
    if health_doc is not None and health_doc.get("status") == "ok":
        checks.append(VerifyCheck(name="health", ok=True, detail="sase core health ok"))
    else:
        checks.append(
            VerifyCheck(
                name="health",
                ok=False,
                detail="sase core health -j did not report ok",
            )
        )

    version = run(
        [str(sase_exe), "version", "-j"],
        timeout=verify_timeout,
        cwd=tmp,
        env=clean,
    )
    version_doc = (
        _parse_json_object(version.stdout) if version.returncode == 0 else None
    )
    host_record: dict[str, object] | None = None
    if version_doc is not None:
        packages = version_doc.get("packages")
        if isinstance(packages, list):
            for entry in packages:
                if isinstance(entry, dict) and entry.get("role") == "host":
                    host_record = entry
                    break
    version_ok = (
        host_record is not None
        and host_record.get("install_type") == "wheel"
        and (
            host_version is None
            or host_record.get("distribution_version") == host_version
        )
    )
    if version_ok:
        checks.append(
            VerifyCheck(
                name="version",
                ok=True,
                detail=f"wheel host at {host_record.get('distribution_version') if host_record else host_version}",
            )
        )
    else:
        checks.append(
            VerifyCheck(
                name="version",
                ok=False,
                detail=f"sase version -j did not report a wheel host at {host_version}",
            )
        )

    kept = install_state.read_python_version(tool_dir)
    if state.python_version is None or kept == state.python_version:
        checks.append(
            VerifyCheck(
                name="interpreter",
                ok=True,
                detail=f"python {kept or 'unknown'} (kept)",
            )
        )
    else:
        checks.append(
            VerifyCheck(
                name="interpreter",
                ok=False,
                detail=f"interpreter changed {state.python_version} -> {kept}",
            )
        )

    agreement = run(
        [str(sase_exe), "update", "-n", "-j"],
        timeout=update_timeout,
        cwd=tmp,
        env=clean,
    )
    if agreement.timed_out:
        checks.append(
            VerifyCheck(
                name="update-agreement",
                ok=False,
                warning_only=True,
                detail="sase update -n -j timed out (inconclusive)",
            )
        )
    else:
        agree_doc = (
            _parse_json_object(agreement.stdout) if agreement.returncode == 0 else None
        )
        if agree_doc is not None and agree_doc.get("mode") == "managed":
            checks.append(
                VerifyCheck(
                    name="update-agreement",
                    ok=True,
                    detail='sase update agrees: mode "managed"',
                )
            )
        else:
            checks.append(
                VerifyCheck(
                    name="update-agreement",
                    ok=False,
                    warning_only=True,
                    detail="sase update -n -j did not report managed (inconclusive)",
                )
            )
    try:
        managed = str(Path(sase_exe).resolve())
        on_path = shutil.which("sase", path=clean.get("PATH"))
        shadow = on_path is not None and str(Path(on_path).resolve()) != managed
    except OSError:
        shadow = False
    if shadow:
        checks.append(
            VerifyCheck(
                name="path-shadow",
                ok=False,
                warning_only=True,
                detail=f"`sase` on PATH is not the managed install ({managed}); "
                "shell files were left untouched",
            )
        )
    else:
        checks.append(
            VerifyCheck(
                name="path-shadow", ok=True, detail=f"sase resolves to {sase_exe}"
            )
        )
    try:
        shutil.rmtree(tmp, ignore_errors=True)
    except OSError:
        pass
    return checks


@dataclass(frozen=True)
class UpdateAgreement:
    """The ``sase update -n -j`` agreement verdict for a dev install."""

    agrees: bool
    warning_only: bool
    detail: str


def classify_update_agreement(doc: Mapping[str, object] | None) -> UpdateAgreement:
    """Decide whether an update dry-run document agrees with a dev install.

    Agreement means ``mode == "dev"`` with no repair planned: no ``role:
    core`` package that would be restored from a published wheel, and no
    reconcile step that exists only because the install is unhealthy (an
    empty command with a reason attached). Pull work from roots that are
    behind their upstream is fine. A missing document is inconclusive;
    the caller maps probe timeouts and failures there too.
    """
    if not isinstance(doc, dict):
        return UpdateAgreement(
            agrees=False,
            warning_only=True,
            detail="sase update -n -j produced no JSON document (inconclusive)",
        )
    mode = doc.get("mode")
    if mode != "dev":
        return UpdateAgreement(
            agrees=False,
            warning_only=False,
            detail=f'sase update -n -j reports mode "{mode}", not "dev"',
        )
    dev = doc.get("dev")
    if not isinstance(dev, dict):
        return UpdateAgreement(
            agrees=False,
            warning_only=False,
            detail="sase update -n -j has no dev plan for this install",
        )
    packages = dev.get("packages")
    if isinstance(packages, list):
        for entry in packages:
            if not isinstance(entry, dict):
                continue
            reason = str(entry.get("reason") or "")
            if entry.get("role") == "core" and "published wheel" in reason:
                return UpdateAgreement(
                    agrees=False,
                    warning_only=False,
                    detail="sase update would restore sase-core-rs from a "
                    f"published wheel: {reason}",
                )
    steps = dev.get("reconcile_steps")
    if isinstance(steps, list):
        for step in steps:
            if not isinstance(step, dict):
                continue
            step_reason = step.get("reason")
            if (not step.get("command")) and step_reason:
                label = step.get("label") or step.get("kind") or "reconcile step"
                return UpdateAgreement(
                    agrees=False,
                    warning_only=False,
                    detail=f"sase update plans repair ({label}): {step_reason}",
                )
    for section in ("packages", "roots"):
        entries = dev.get(section)
        if not isinstance(entries, list):
            continue
        for entry in entries:
            if isinstance(entry, dict) and entry.get("fetch_error"):
                return UpdateAgreement(
                    agrees=False,
                    warning_only=True,
                    detail="sase update -n -j hit fetch errors (inconclusive)",
                )
    return UpdateAgreement(
        agrees=True,
        warning_only=False,
        detail='sase update agrees: mode "dev", no repair planned',
    )


def _same_checkout(left: str | None, right: str | Path | None) -> bool:
    """Return whether two checkout paths name the same directory."""
    if not left or right is None:
        return False
    try:
        return os.path.realpath(left) == os.path.realpath(str(right))
    except OSError:
        return False


def verify_dev_install(
    *,
    plan: install_plan.InstallPlan,
    state: install_state.InstallState,
    tool_dir: str | Path,
    sase_exe: str | Path,
    tool_python: str | Path,
    env: Mapping[str, str],
    run: Callable[..., RunnerResult],
    update_timeout: float = UPDATE_AGREE_TIMEOUT_SECONDS,
    verify_timeout: float = VERIFY_TIMEOUT_SECONDS,
) -> list[VerifyCheck]:
    """Verify a dev swap from a neutral cwd with a scrubbed environment.

    Every probe runs the tool environment's own executables with
    ``PYTHONPATH``/``PYTHONHOME``/``VIRTUAL_ENV`` removed so an activated
    checkout ``.venv`` can neither shadow the install nor fake a pass.
    """
    checks: list[VerifyCheck] = []
    clean = scrubbed_env(env)
    tmp = Path(tempfile.mkdtemp(prefix="sase-install-verify-"))
    checkout = plan.checkout_root
    core = plan.core_dir
    expected = {
        "sase": os.path.join(checkout, "src", "sase"),
        "sase_core_rs": os.path.join(core, "crates", "sase_core_py", "python"),
    }

    import_probe = (
        "import json,sys;"
        "out={};"
        "[out.__setitem__(sys.argv[i],__import__(sys.argv[i]).__file__) "
        "for i in range(1,len(sys.argv))];"
        "print(json.dumps(out))"
    )
    locations: dict[str, str] = {}
    imports_ok = True
    result = run(
        [str(tool_python), "-I", "-c", import_probe, "sase", "sase_core_rs"],
        timeout=verify_timeout,
        cwd=tmp,
        env=clean,
    )
    if result.returncode == 0:
        try:
            payload = json.loads(result.stdout.strip() or "{}")
            locations = (
                {str(k): str(v) for k, v in payload.items()}
                if isinstance(payload, dict)
                else {}
            )
        except ValueError:
            locations = {}
    for module, root in expected.items():
        location = locations.get(module, "")
        try:
            here = os.path.realpath(location) if location else ""
            want = os.path.realpath(root)
            if not here or (here != want and not here.startswith(want + os.sep)):
                imports_ok = False
        except OSError:
            imports_ok = False
    if imports_ok:
        checks.append(
            VerifyCheck(
                name="imports",
                ok=True,
                detail="sase and sase_core_rs import from this checkout and core",
            )
        )
    else:
        checks.append(
            VerifyCheck(
                name="imports",
                ok=False,
                detail=f"sase -> {locations.get('sase') or 'missing'}; "
                f"sase_core_rs -> {locations.get('sase_core_rs') or 'missing'}",
            )
        )

    health = run(
        [str(sase_exe), "core", "health", "-j"],
        timeout=verify_timeout,
        cwd=tmp,
        env=clean,
    )
    health_doc = _parse_json_object(health.stdout) if health.returncode == 0 else None
    if health_doc is not None and health_doc.get("status") == "ok":
        checks.append(VerifyCheck(name="health", ok=True, detail="sase core health ok"))
    else:
        checks.append(
            VerifyCheck(
                name="health",
                ok=False,
                detail="sase core health -j did not report ok",
            )
        )

    checker = os.path.join(checkout, "tools", "check_sase_core_rs_bindings")
    bindings = run(
        [str(tool_python), checker, "--src", os.path.join(checkout, "src", "sase")],
        timeout=verify_timeout,
        cwd=tmp,
        env=clean,
    )
    if bindings.returncode == 0:
        checks.append(
            VerifyCheck(
                name="bindings",
                ok=True,
                detail="sase-core-rs exposes the bindings sase requires",
            )
        )
    else:
        tail = (bindings.stderr.strip() or bindings.stdout.strip()).splitlines()
        checks.append(
            VerifyCheck(
                name="bindings",
                ok=False,
                detail="bindings check failed: "
                + (tail[-1].strip() if tail else "unknown error"),
            )
        )

    version = run(
        [str(sase_exe), "version", "-j"],
        timeout=verify_timeout,
        cwd=tmp,
        env=clean,
    )
    version_doc = (
        _parse_json_object(version.stdout) if version.returncode == 0 else None
    )
    host_record: dict[str, object] | None = None
    if version_doc is not None:
        packages = version_doc.get("packages")
        if isinstance(packages, list):
            for entry in packages:
                if isinstance(entry, dict) and entry.get("role") == "host":
                    host_record = entry
                    break
    source_root = str(host_record.get("source_root") or "") if host_record else ""
    version_ok = (
        host_record is not None
        and host_record.get("install_type") == "editable"
        and _same_checkout(source_root, checkout)
    )
    if version_ok:
        checks.append(
            VerifyCheck(
                name="version",
                ok=True,
                detail=f"editable host at {host_record.get('source_root') if host_record else checkout}",
            )
        )
    else:
        checks.append(
            VerifyCheck(
                name="version",
                ok=False,
                detail=f"sase version -j did not report an editable host at {checkout}",
            )
        )

    lsp = run(
        [str(sase_exe), "lsp", "--version"],
        timeout=verify_timeout,
        cwd=tmp,
        env=clean,
    )
    if lsp.returncode == 0:
        checks.append(
            VerifyCheck(
                name="lsp",
                ok=True,
                detail=(lsp.stdout.strip().splitlines() or ["sase lsp works"])[0],
            )
        )
    else:
        checks.append(
            VerifyCheck(
                name="lsp",
                ok=False,
                detail="sase lsp --version did not succeed",
            )
        )

    kept = install_state.read_python_version(tool_dir)
    if state.python_version is None or kept == state.python_version:
        checks.append(
            VerifyCheck(
                name="interpreter",
                ok=True,
                detail=f"python {kept or 'unknown'} (kept)",
            )
        )
    else:
        checks.append(
            VerifyCheck(
                name="interpreter",
                ok=False,
                detail=f"interpreter changed {state.python_version} -> {kept}",
            )
        )

    agreement = run(
        [str(sase_exe), "update", "-n", "-j"],
        timeout=update_timeout,
        cwd=tmp,
        env=clean,
    )
    if agreement.timed_out:
        checks.append(
            VerifyCheck(
                name="update-agreement",
                ok=False,
                warning_only=True,
                detail="sase update -n -j timed out (inconclusive)",
            )
        )
    else:
        agree_doc = (
            _parse_json_object(agreement.stdout) if agreement.returncode == 0 else None
        )
        verdict = classify_update_agreement(agree_doc)
        checks.append(
            VerifyCheck(
                name="update-agreement",
                ok=verdict.agrees,
                warning_only=verdict.warning_only,
                detail=verdict.detail,
            )
        )

    managed_lsp = Path(tool_dir) / "bin" / install_state.LSP_BINARY_NAME
    try:
        on_path = shutil.which("sase-macro-lsp", path=clean.get("PATH"))
        shadow = on_path is not None and os.path.realpath(on_path) != os.path.realpath(
            str(managed_lsp)
        )
        cargo_shadow = (
            shadow
            and on_path is not None
            and on_path.startswith(
                str(Path(clean.get("HOME", str(Path.home()))) / ".cargo" / "bin")
                + os.sep
            )
        )
    except OSError:
        cargo_shadow = False
    if cargo_shadow:
        checks.append(
            VerifyCheck(
                name="lsp-shadow",
                ok=False,
                warning_only=True,
                detail="a stale sase-macro-lsp in ~/.cargo/bin shadows the "
                "managed one; remove it with `cargo uninstall sase_macro_lsp`",
            )
        )
    try:
        shutil.rmtree(tmp, ignore_errors=True)
    except OSError:
        pass
    return checks


def quick_health_ok(
    *,
    sase_exe: str | Path,
    env: Mapping[str, str],
    run: Callable[..., RunnerResult],
    timeout: float = HEALTH_TIMEOUT_SECONDS,
) -> bool:
    """Return whether the managed install answers a fast health probe."""
    tmp = Path(tempfile.mkdtemp(prefix="sase-install-health-"))
    try:
        result = run(
            [str(sase_exe), "core", "health", "-j"],
            timeout=timeout,
            cwd=tmp,
            env=scrubbed_env(env),
        )
    finally:
        try:
            shutil.rmtree(tmp, ignore_errors=True)
        except OSError:
            pass
    if result.returncode != 0:
        return False
    doc = _parse_json_object(result.stdout)
    return doc is not None and doc.get("status") == "ok"


_METADATA_PROBE = "\n".join(
    [
        "import importlib.metadata as _m, json as _j, sys as _s",
        "_o = {}",
        "for _n in _s.argv[1:]:",
        "    try:",
        "        _o[_n] = _m.version(_n)",
        "    except _m.PackageNotFoundError:",
        "        _o[_n] = None",
        "print(_j.dumps(_o))",
    ]
)


def missing_plugin_names(
    desired: Sequence[str],
    *,
    tool_python: str | Path,
    env: Mapping[str, str],
    run: Callable[..., RunnerResult],
    timeout: float = VERIFY_TIMEOUT_SECONDS,
) -> list[str]:
    """Return desired plugin distributions absent from the new environment.

    Best-effort: any probe error yields ``[]`` (nothing is printed), so a
    fresh install never fails because the suggestion probe failed.
    """
    names = [name for name in desired if name]
    if not names:
        return []
    tmp = Path(tempfile.mkdtemp(prefix="sase-install-plugins-"))
    try:
        try:
            result = run(
                [str(tool_python), "-I", "-c", _METADATA_PROBE, *names],
                timeout=timeout,
                cwd=tmp,
                env=scrubbed_env(env),
            )
        except OSError:
            return []
    finally:
        try:
            shutil.rmtree(tmp, ignore_errors=True)
        except OSError:
            pass
    if result.returncode != 0:
        return []
    try:
        payload = json.loads(result.stdout.strip() or "{}")
    except ValueError:
        return []
    if not isinstance(payload, dict):
        return []
    missing = [name for name in names if not payload.get(name)]
    return missing


def scheduler_running(sase_home: str | Path) -> bool:
    """Probe scheduler liveness with stdlib only (mirrors ``axe`` probing).

    First the orchestrator lifecycle lock: a busy exclusive ``flock`` means a
    live scheduler holds it. Otherwise fall back to pid-file liveness for the
    orchestrator and legacy pid files.
    """
    axe_dir = Path(sase_home) / "axe"
    lock_file = axe_dir / "orchestrator.lock"
    try:
        fd = os.open(lock_file, os.O_RDWR | os.O_CREAT, 0o666)
    except OSError:
        fd = None
    if fd is not None:
        try:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                return True
            except OSError:
                pass
            else:
                fcntl.flock(fd, fcntl.LOCK_UN)
        finally:
            try:
                os.close(fd)
            except OSError:
                pass
    for pid_file in (axe_dir / "orchestrator.pid", axe_dir / "pid"):
        try:
            raw = pid_file.read_text(encoding="utf-8").strip()
        except OSError:
            continue
        try:
            pid = int(raw)
        except ValueError:
            continue
        if pid > 0 and is_process_running(pid):
            return True
    return False


@dataclass(frozen=True)
class PipelineOptions:
    """Run-scoped choices for the install pipelines (no side effects to build)."""

    env: Mapping[str, str]
    sase_home: str
    tool_dir: str
    bin_dir: str | Path | None
    verbose: bool = False
    quiet: bool = False
    as_json: bool = False
    force: bool = False
    lock_timeout: float = LOCK_TIMEOUT_SECONDS
    swap_timeout: float = SWAP_TIMEOUT_SECONDS
    lock_disabled: bool = False
    sync: bool = False


@dataclass(frozen=True)
class PipelineOutcome:
    """The pipeline result: exit code plus the summary already printed."""

    exit_code: int
    log_path: str
    noop: bool = False


def _open_log(log_path: Path) -> TextIO:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    return log_path.open("a", encoding="utf-8")


def run_pypi_pipeline(
    *,
    plan: install_plan.InstallPlan,
    state: install_state.InstallState,
    options: PipelineOptions,
    stdout: TextIO,
    stderr: TextIO,
    run: Callable[..., RunnerResult] = default_runner,
    sleep: Callable[[float], None] = time.sleep,
) -> PipelineOutcome:
    """Run the PyPI execution pipeline; return the process outcome.

    ``preflight``/``plan``/``confirm`` already happened in the entry point:
    this drives ``lock ─► swap ─► verify ─► restart ─► summary`` with the
    progress renderer, writing every command and its output to the run log.
    """
    out = stdout
    err = stderr
    env = options.env
    sase_home = options.sase_home
    tool_dir = Path(options.tool_dir)

    log_path = log_path_for(sase_home)
    log = _open_log(log_path)

    def log_command(
        argv: Sequence[str | Path], result: RunnerResult, *, cwd: object = None
    ) -> None:
        log.write(f"$ {' '.join(shlex.quote(str(p)) for p in argv)}\n")
        if cwd is not None:
            log.write(f"cwd: {cwd}\n")
        if result.stdout:
            log.write(result.stdout)
            if not result.stdout.endswith("\n"):
                log.write("\n")
        if result.stderr:
            log.write(f"[stderr]\n{result.stderr}")
            if not result.stderr.endswith("\n"):
                log.write("\n")
        log.write(f"exit: {result.returncode}\n")
        log.flush()

    def fail(
        step: str,
        message: str,
        backup: BackupInfo | None,
        *,
        outcome: str = "failed",
    ) -> PipelineOutcome:
        tail = install_ui.tail_lines(message, 20)
        block = install_ui.render_failure_block(
            step_title=step,
            log_path=str(log_path),
            tail=tail,
            restore_command=backup.restore_command if backup is not None else None,
        )
        if options.as_json:
            out.write(
                install_ui.render_json(
                    plan,
                    dry_run=False,
                    outcome=outcome,
                    error=f"{step}: {message.splitlines()[0] if message else 'failed'}",
                    log_path=str(log_path),
                )
            )
        err.write(block + "\n")
        log.write(f"FAILED {step}: {message}\n")
        log.close()
        return PipelineOutcome(exit_code=1, log_path=str(log_path))

    tty = False
    isatty = getattr(err, "isatty", None)
    if callable(isatty):
        try:
            tty = bool(isatty())
        except (OSError, ValueError):
            tty = False
    use_live = tty and not options.verbose and not options.quiet and not options.as_json
    progress = install_ui.Progress(
        err,
        mode="quiet"
        if (options.quiet or options.as_json)
        else ("live" if use_live else "plain"),
        color=install_env.colors_enabled(env, err) and not options.verbose,
    )

    sase_exe = managed_sase_exe(tool_dir=tool_dir, bin_dir=options.bin_dir)
    tool_python = tool_python_for(tool_dir)

    if plan.noop and not options.force:
        progress.start("verify", "Probe current install")
        healthy = quick_health_ok(sase_exe=sase_exe, env=env, run=run)
        if healthy:
            progress.finish("ok", "already current and healthy")
            log.write("noop: already current and healthy\n")
            log.close()
            if options.as_json:
                out.write(install_ui.render_json(plan, dry_run=False, outcome="noop"))
            else:
                out.write(install_ui.render_noop_line(plan) + "\n")
            return PipelineOutcome(exit_code=0, log_path=str(log_path), noop=True)
        progress.finish("warn", "plan is current but health failed; reinstalling")

    was_running = scheduler_running(sase_home)

    advisory = count_live_advisory_runners(sase_home)
    if advisory:
        progress.warn(
            f"{advisory} agent runner(s) are running from this install; "
            "a swap now can break their deferred imports."
        )

    progress.start("lock", "Take the code-swap lock")

    def on_wait(holder: str, elapsed: float) -> None:
        progress.tick(f"waiting for {holder}")

    try:
        lock, blocker = acquire_swap_lock(
            lock_path_for(sase_home),
            op="install.pypi",
            command=["just", "install"],
            timeout=options.lock_timeout,
            disabled=options.lock_disabled
            or env.get(install_env.DISABLE_LOCK_ENV_VAR) == "1",
            sleep=sleep,
            on_wait=on_wait,
        )
    except OSError as exc:
        progress.finish("fail", "lock error")
        return fail("Lock", f"could not take the code-swap lock: {exc}", None)
    if lock is None:
        progress.finish("fail", "lock busy")
        return fail(
            "Lock",
            f"another source-tree swap is in progress: {blocker}",
            None,
        )
    progress.finish("ok", "code-swap writer lock")
    try:
        progress.start("swap", "Install from PyPI")
        backup = write_backup(backup_path_for(sase_home), state=state, env=env)
        log.write(f"backup: {backup.path}\nrestore: {backup.restore_command}\n")
        log.flush()

        if plan.overrides_lines:
            overrides_target = (
                Path(plan.overrides_path)
                if plan.overrides_path is not None
                else install_env.editable_overrides_path(env)
            )
            try:
                overrides_target.parent.mkdir(parents=True, exist_ok=True)
                overrides_target.write_text(
                    "\n".join(plan.overrides_lines) + "\n", encoding="utf-8"
                )
                log.write(
                    f"overrides: wrote {len(plan.overrides_lines)} lines to "
                    f"{overrides_target}\n"
                )
            except OSError as exc:
                progress.finish("fail", "overrides write failed")
                return fail("Swap", f"could not write overrides file: {exc}", backup)
        else:
            log.write("overrides: no editables remain; leaving the file untouched\n")

        argv = swap_argv_for(plan, tool_python=tool_python, env_exists=state.env_exists)
        log.write(f"$ {' '.join(shlex.quote(p) for p in argv)}\n")
        log.flush()
        result = run(argv, timeout=options.swap_timeout, cwd=None, env=dict(env))
        log_command(argv, result)
        if options.verbose:
            for line in (result.stdout + result.stderr).splitlines():
                progress.note(f"│ {line}")
        if result.returncode != 0:
            progress.finish("fail", f"uv exited {result.returncode}")
            detail = (result.stderr.strip() or result.stdout.strip())[-2000:]
            return fail(
                "Swap", detail or f"uv tool install exited {result.returncode}", backup
            )
        progress.finish("ok", f"{len(argv)}-arg uv swap")

        progress.start("verify", "Verify the new install")
        verify_checks = verify_pypi_install(
            plan=plan,
            state=state,
            tool_dir=tool_dir,
            sase_exe=sase_exe,
            tool_python=tool_python,
            env=env,
            run=run,
        )
        hard_failures = [c for c in verify_checks if not c.ok and not c.warning_only]
        warnings = [c for c in verify_checks if not c.ok and c.warning_only]
        for check in verify_checks:
            log.write(
                f"verify {check.name}: {'ok' if check.ok else 'FAIL'} {check.detail}\n"
            )
        log.flush()
        if hard_failures:
            progress.finish("fail", hard_failures[0].detail)
            detail = "; ".join(f"{c.name}: {c.detail}" for c in hard_failures)
            for check in warnings:
                progress.warn(check.detail)
            return fail("Verify", detail, backup)
        progress.finish("ok", "health, version, and interpreter agree")
        for check in warnings:
            progress.warn(check.detail)
        for warning in plan.warnings:
            progress.warn(warning)

        progress.start("restart", "Restart the scheduler")
        if was_running:
            restart = run(
                [str(sase_exe), "scheduler", "restart"],
                timeout=RESTART_TIMEOUT_SECONDS,
                cwd=None,
                env=dict(env),
            )
            log_command([str(sase_exe), "scheduler", "restart"], restart)
            if restart.returncode != 0:
                progress.finish("warn", "scheduler restart failed; install is fine")
                progress.warn(
                    "the scheduler restart failed; your install is unaffected."
                )
            else:
                progress.finish("ok", "scheduler restarted")
        else:
            progress.finish("skip", "scheduler was not running")

        summary = install_ui.render_pypi_success(plan)
        lines = [summary]
        if plan.fresh:
            desired_plugins = [row.name for row in plan.rows if row.role == "plugin"]
            missing = missing_plugin_names(
                desired_plugins, tool_python=tool_python, env=env, run=run
            )
            if missing:
                lines.append(f"Next: sase plugin install {' '.join(missing)}")
        progress.finish("ok", "done")
        log.write("SUCCESS\n" + summary + "\n")
        log.close()
        if options.as_json:
            out.write(
                install_ui.render_json(
                    plan, dry_run=False, outcome="success", log_path=str(log_path)
                )
            )
        elif options.quiet:
            out.write(install_ui.render_summary_line(plan, dry_run=False) + "\n")
        else:
            out.write("\n".join(lines) + "\n")
        return PipelineOutcome(exit_code=0, log_path=str(log_path))
    finally:
        lock.release()


def _dev_sync_paths(plan: install_plan.InstallPlan) -> list[str]:
    """Return the checkouts ``--sync`` pulls for a dev run."""
    paths = [plan.checkout_root]
    if Path(plan.core_dir).is_dir():
        paths.append(plan.core_dir)
    for row in plan.rows:
        if (
            row.role == "plugin"
            and row.target.kind == "editable"
            and row.target.path
            and Path(row.target.path).is_dir()
        ):
            paths.append(row.target.path)
    return paths


def _git_short(repo: str | Path) -> str:
    """Return ``HEAD`` shortened for summaries, or ``"unknown"``."""
    try:
        completed = subprocess.run(
            ["git", "rev-parse", f"--short={SUMMARY_SHORT_LENGTH}", "HEAD"],
            check=False,
            capture_output=True,
            text=True,
            timeout=SUMMARY_GIT_TIMEOUT_SECONDS,
            stdin=subprocess.DEVNULL,
            cwd=str(repo),
        )
    except (OSError, subprocess.TimeoutExpired):
        return "unknown"
    short = completed.stdout.strip() if completed.returncode == 0 else ""
    return short or "unknown"


def dev_summary_shas(
    *,
    checkout_root: str | Path,
    core_dir: str | Path,
) -> tuple[str, str, str, int | None]:
    """Return ``(checkout, core, pin)`` SHAs plus core commits past the pin.

    Every answer is best-effort: unresolvable SHAs become ``"unknown"``
    and an uncountable distance becomes ``None``.
    """
    try:
        pin = install_core.read_pin(checkout_root)
    except install_core.CorePairingError:
        pin = ""
    pin_short = pin[:SUMMARY_SHORT_LENGTH] if pin else "unknown"
    ahead = install_core.commits_ahead(core_dir, pin, "HEAD") if pin else None
    return (
        _git_short(checkout_root),
        _git_short(core_dir),
        pin_short,
        ahead,
    )


def _installed_core_matches(
    state: install_state.InstallState, core_dir: str | Path
) -> bool:
    """Return whether the installed core is editable from *core_dir*."""
    dist = state.find_dist(install_plan.CORE_DIST_NAME)
    if dist is None or not dist.editable_path:
        return False
    return _same_checkout(dist.editable_path, core_dir)


def _dev_stamp_current(
    *,
    tool_dir: str | Path,
    core_dir: str | Path,
    state: install_state.InstallState,
) -> bool:
    """Return whether the tool env's core stamp matches the core identity.

    A missing stamp never matches; an uncomputable identity skips the
    freshness check (it never counts as matching any stamp either).
    """
    stamp = state.core_stamp
    if not isinstance(stamp, dict) or not stamp:
        return False
    try:
        identity = core_identity.compute_identity(Path(core_dir))
    except Exception:  # noqa: BLE001 - a probe failure skips the check
        return True
    if identity is None:
        return True
    return stamp.get("head") == identity.get("head") and stamp.get(
        "dirty"
    ) == identity.get("dirty")


def _reapply_dev_core(
    *,
    plan: install_plan.InstallPlan,
    tool_dir: str | Path,
    env: Mapping[str, str],
    run: Callable[..., RunnerResult],
    log_command: Callable[..., None],
    progress: install_ui.Progress,
    verbose: bool,
) -> tuple[str | None, str | None]:
    """Rebuild the editable core and LSP; return ``(error, stamp_warning)``.

    The core identity is captured before the rebuild and compared against
    the stamp the rebuild writes: a mismatch only warns, because the tree
    may have moved mid-build.
    """
    try:
        before = core_identity.compute_identity(Path(plan.core_dir))
    except Exception:  # noqa: BLE001 - an uncomputable identity skips the check
        before = None
    argv = [
        "just",
        "-f",
        str(Path(plan.checkout_root) / "Justfile"),
        "rust-dev-install-uv-tool",
    ]
    re_env = dict(env)
    re_env["SASE_RUST_DEV_PROFILE"] = REAPPLY_RUST_PROFILE
    result = run(argv, timeout=REAPPLY_TIMEOUT_SECONDS, cwd=None, env=re_env)
    log_command(argv, result)
    if verbose:
        for line in (result.stdout + result.stderr).splitlines():
            progress.note(f"│ {line}")
    if result.timed_out:
        return (
            "just rust-dev-install-uv-tool timed out after "
            f"{REAPPLY_TIMEOUT_SECONDS:.0f}s; the tool environment now holds "
            "a PyPI sase-core build. Rerun just install-dev.",
            None,
        )
    if result.returncode != 0:
        tail = (result.stderr.strip() or result.stdout.strip())[-2000:]
        return (
            "just rust-dev-install-uv-tool exited "
            f"{result.returncode}: {tail or 'unknown error'}; the tool "
            "environment now holds a PyPI sase-core build. Rerun "
            "just install-dev.",
            None,
        )
    warning = None
    if before is not None:
        stamp = core_identity.read_stamp(Path(tool_dir))
        if stamp is None or stamp != before:
            warning = "sase-core changed during the build; rerun just install-dev"
    return (None, warning)


def run_dev_pipeline(
    *,
    plan: install_plan.InstallPlan,
    state: install_state.InstallState,
    options: PipelineOptions,
    stdout: TextIO,
    stderr: TextIO,
    run: Callable[..., RunnerResult] = default_runner,
    sleep: Callable[[float], None] = time.sleep,
) -> PipelineOutcome:
    """Run the dev execution pipeline; return the process outcome.

    ``preflight``/``plan``/``confirm`` already happened in the entry point:
    this drives ``prepare ─► lock ─► swap ─► re-apply ─► verify ─► restart
    ─► summary`` with the progress renderer, writing every command and its
    output to the run log.
    """
    out = stdout
    err = stderr
    env = options.env
    sase_home = options.sase_home
    tool_dir = Path(options.tool_dir)
    checkout = plan.checkout_root
    core = plan.core_dir

    log_path = log_path_for(sase_home)
    log = _open_log(log_path)

    def log_command(
        argv: Sequence[str | Path], result: RunnerResult, *, cwd: object = None
    ) -> None:
        log.write(f"$ {' '.join(shlex.quote(str(p)) for p in argv)}\n")
        if cwd is not None:
            log.write(f"cwd: {cwd}\n")
        if result.stdout:
            log.write(result.stdout)
            if not result.stdout.endswith("\n"):
                log.write("\n")
        if result.stderr:
            log.write(f"[stderr]\n{result.stderr}")
            if not result.stderr.endswith("\n"):
                log.write("\n")
        log.write(f"exit: {result.returncode}\n")
        log.flush()

    def fail(
        step: str,
        message: str,
        backup: BackupInfo | None,
        *,
        outcome: str = "failed",
    ) -> PipelineOutcome:
        tail = install_ui.tail_lines(message, 20)
        block = install_ui.render_failure_block(
            step_title=step,
            log_path=str(log_path),
            tail=tail,
            restore_command=backup.restore_command if backup is not None else None,
        )
        if options.as_json:
            out.write(
                install_ui.render_json(
                    plan,
                    dry_run=False,
                    outcome=outcome,
                    error=f"{step}: {message.splitlines()[0] if message else 'failed'}",
                    log_path=str(log_path),
                )
            )
        err.write(block + "\n")
        log.write(f"FAILED {step}: {message}\n")
        log.close()
        return PipelineOutcome(exit_code=1, log_path=str(log_path))

    tty = False
    isatty = getattr(err, "isatty", None)
    if callable(isatty):
        try:
            tty = bool(isatty())
        except (OSError, ValueError):
            tty = False
    use_live = tty and not options.verbose and not options.quiet and not options.as_json
    progress = install_ui.Progress(
        err,
        mode="quiet"
        if (options.quiet or options.as_json)
        else ("live" if use_live else "plain"),
        color=install_env.colors_enabled(env, err) and not options.verbose,
    )

    sase_exe = managed_sase_exe(tool_dir=tool_dir, bin_dir=options.bin_dir)
    tool_python = tool_python_for(tool_dir)

    if plan.noop and not options.force:
        progress.start("verify", "Probe current install")
        reasons: list[str] = []
        if not quick_health_ok(sase_exe=sase_exe, env=env, run=run):
            reasons.append("health probe failed")
        if not _installed_core_matches(state, core):
            reasons.append("installed core is not the paired checkout")
        if not _dev_stamp_current(tool_dir=tool_dir, core_dir=core, state=state):
            reasons.append("core stamp is stale")
        if not (tool_dir / "bin" / install_state.LSP_BINARY_NAME).exists():
            reasons.append("LSP binary is missing")
        if not reasons:
            progress.finish("ok", "already current and healthy")
            log.write("noop: already current and healthy\n")
            log.close()
            checkout_short, core_short, _, _ = dev_summary_shas(
                checkout_root=checkout, core_dir=core
            )
            noop_line = install_ui.render_noop_line(
                plan, checkout_short=checkout_short, core_short=core_short
            )
            if options.as_json:
                out.write(install_ui.render_json(plan, dry_run=False, outcome="noop"))
            else:
                out.write(noop_line + "\n")
            return PipelineOutcome(exit_code=0, log_path=str(log_path), noop=True)
        progress.finish("warn", f"{'; '.join(reasons)}; reinstalling")

    was_running = scheduler_running(sase_home)

    advisory = count_live_advisory_runners(sase_home)
    if advisory:
        progress.warn(
            f"{advisory} agent runner(s) are running from this install; "
            "a swap now can break their deferred imports."
        )

    progress.start("prepare", "Prepare sase-core")
    if options.sync:
        sync_results = install_core.sync_repos(
            _dev_sync_paths(plan), merge=True, env=env
        )
        for sync_result in sync_results:
            log.write(
                f"sync {sync_result.path}: "
                f"{'ok' if sync_result.ok else 'FAIL'} {sync_result.detail}\n"
            )
        log.flush()
        sync_failures = [item for item in sync_results if not item.ok]
        if sync_failures:
            progress.finish("fail", "sync gate failed")
            lines = ["--sync refused to merge:"] + [
                f"  {item.path}: {item.detail}" for item in sync_failures
            ]
            return fail("Sync", "\n".join(lines), None)
        for sync_result in sync_results:
            if not sync_result.skipped:
                progress.note(f"synced {sync_result.path}: {sync_result.detail}")
    try:
        pairing = install_core.pair_core(checkout, core, env=env)
    except install_core.CorePairingError as exc:
        progress.finish("fail", "core pairing failed")
        return fail("Prepare", str(exc), None)
    if pairing.action == "clone":
        remote = pairing.remote_url or install_core.core_remote(env)
        progress.tick(f"cloning sase-core from {remote}")
        clone_argv = ["git", "clone", remote, core]
        cloned = run(
            clone_argv,
            timeout=PREPARE_CLONE_TIMEOUT_SECONDS,
            cwd=None,
            env=dict(env),
        )
        log_command(clone_argv, cloned)
        if cloned.returncode != 0:
            progress.finish("fail", "core clone failed")
            tail = (cloned.stderr.strip() or cloned.stdout.strip())[-2000:]
            return fail(
                "Prepare",
                f"could not clone sase-core from {remote}: "
                f"{tail or 'git clone failed'}",
                None,
            )
        progress.note(f"cloned sase-core -> {core}")
        try:
            pairing = install_core.pair_core(checkout, core, env=env)
        except install_core.CorePairingError as exc:
            progress.finish("fail", "core pairing failed")
            return fail("Prepare", str(exc), None)
    if pairing.action == "fast-forward":
        upstream = pairing.upstream
        if not upstream:
            progress.finish("fail", "core fast-forward failed")
            return fail(
                "Prepare",
                "sase-core needs a fast-forward but has no upstream",
                None,
            )
        merge_argv = ["git", "merge", "--ff-only", upstream]
        merged = run(
            merge_argv,
            timeout=PREPARE_FF_TIMEOUT_SECONDS,
            cwd=core,
            env=dict(env),
        )
        log_command(merge_argv, merged, cwd=core)
        if merged.returncode != 0:
            progress.finish("fail", "core fast-forward failed")
            tail = (merged.stderr.strip() or merged.stdout.strip())[-2000:]
            return fail(
                "Prepare",
                f"could not fast-forward sase-core to {upstream}: "
                f"{tail or 'git merge failed'}",
                None,
            )
        progress.note(f"fast-forwarded sase-core to {upstream}")
    build_check = install_core.pre_swap_build_check(
        core, tool_python=tool_python, env=env
    )
    log.write(f"build-check: {build_check.method} {build_check.detail}\n")
    log.flush()
    if not build_check.ok:
        progress.finish("fail", "core build check failed")
        return fail("Prepare sase-core", build_check.detail, None)
    progress.finish("ok", f"core ready ({build_check.detail})")

    progress.start("lock", "Take the code-swap lock")

    def on_wait(holder: str, elapsed: float) -> None:
        progress.tick(f"waiting for {holder}")

    try:
        lock, blocker = acquire_swap_lock(
            lock_path_for(sase_home),
            op="install.dev",
            command=["just", "install-dev"],
            timeout=options.lock_timeout,
            disabled=options.lock_disabled
            or env.get(install_env.DISABLE_LOCK_ENV_VAR) == "1",
            sleep=sleep,
            on_wait=on_wait,
        )
    except OSError as exc:
        progress.finish("fail", "lock error")
        return fail("Lock", f"could not take the code-swap lock: {exc}", None)
    if lock is None:
        progress.finish("fail", "lock busy")
        return fail(
            "Lock",
            f"another source-tree swap is in progress: {blocker}",
            None,
        )
    progress.finish("ok", "code-swap writer lock")
    try:
        progress.start("swap", "Install this checkout")
        backup = write_backup(backup_path_for(sase_home), state=state, env=env)
        log.write(f"backup: {backup.path}\nrestore: {backup.restore_command}\n")
        log.flush()

        if plan.overrides_lines:
            overrides_target = (
                Path(plan.overrides_path)
                if plan.overrides_path is not None
                else install_env.editable_overrides_path(env)
            )
            try:
                overrides_target.parent.mkdir(parents=True, exist_ok=True)
                overrides_target.write_text(
                    "\n".join(plan.overrides_lines) + "\n", encoding="utf-8"
                )
                log.write(
                    f"overrides: wrote {len(plan.overrides_lines)} lines to "
                    f"{overrides_target}\n"
                )
            except OSError as exc:
                progress.finish("fail", "overrides write failed")
                return fail("Swap", f"could not write overrides file: {exc}", backup)
        else:
            log.write("overrides: no editables remain; leaving the file untouched\n")

        argv = swap_argv_for(plan, tool_python=tool_python, env_exists=state.env_exists)
        log.write(f"$ {' '.join(shlex.quote(p) for p in argv)}\n")
        log.flush()
        result = run(argv, timeout=options.swap_timeout, cwd=None, env=dict(env))
        log_command(argv, result)
        if options.verbose:
            for line in (result.stdout + result.stderr).splitlines():
                progress.note(f"│ {line}")
        if result.returncode != 0:
            progress.finish("fail", f"uv exited {result.returncode}")
            detail = (result.stderr.strip() or result.stdout.strip())[-2000:]
            return fail(
                "Swap", detail or f"uv tool install exited {result.returncode}", backup
            )
        progress.finish("ok", f"{len(argv)}-arg uv swap")

        progress.start("re-apply", "Rebuild the editable core and LSP")
        reapply_error, stamp_warning = _reapply_dev_core(
            plan=plan,
            tool_dir=tool_dir,
            env=env,
            run=run,
            log_command=log_command,
            progress=progress,
            verbose=options.verbose,
        )
        if reapply_error is not None:
            progress.finish("fail", "core re-apply failed")
            return fail("Re-apply", reapply_error, backup)
        progress.finish("ok", "editable core and LSP rebuilt")
        if stamp_warning is not None:
            progress.warn(stamp_warning)

        progress.start("verify", "Verify the new install")
        verify_checks = verify_dev_install(
            plan=plan,
            state=state,
            tool_dir=tool_dir,
            sase_exe=sase_exe,
            tool_python=tool_python,
            env=env,
            run=run,
        )
        hard_failures = [c for c in verify_checks if not c.ok and not c.warning_only]
        warnings = [c for c in verify_checks if not c.ok and c.warning_only]
        for check in verify_checks:
            log.write(
                f"verify {check.name}: {'ok' if check.ok else 'FAIL'} {check.detail}\n"
            )
        log.flush()
        if hard_failures:
            progress.finish("fail", hard_failures[0].detail)
            detail = "; ".join(f"{c.name}: {c.detail}" for c in hard_failures)
            for check in warnings:
                progress.warn(check.detail)
            return fail("Verify", detail, backup)
        progress.finish("ok", "checkout, core, and update agree")
        for check in warnings:
            progress.warn(check.detail)
        for warning in plan.warnings:
            progress.warn(warning)

        progress.start("restart", "Restart the scheduler")
        if was_running:
            restart = run(
                [str(sase_exe), "scheduler", "restart"],
                timeout=RESTART_TIMEOUT_SECONDS,
                cwd=None,
                env=dict(env),
            )
            log_command([str(sase_exe), "scheduler", "restart"], restart)
            if restart.returncode != 0:
                progress.finish("warn", "scheduler restart failed; install is fine")
                progress.warn(
                    "the scheduler restart failed; your install is unaffected."
                )
            else:
                progress.finish("ok", "scheduler restarted")
        else:
            progress.finish("skip", "scheduler was not running")

        checkout_short, core_short, pin_short, ahead = dev_summary_shas(
            checkout_root=checkout, core_dir=core
        )
        summary = install_ui.render_dev_success(
            plan,
            checkout_short=checkout_short,
            core_short=core_short,
            pin_short=pin_short,
            commits_past_pin=ahead,
        )
        progress.finish("ok", "done")
        log.write("SUCCESS\n" + summary + "\n")
        log.close()
        if options.as_json:
            out.write(
                install_ui.render_json(
                    plan, dry_run=False, outcome="success", log_path=str(log_path)
                )
            )
        elif options.quiet:
            out.write(install_ui.render_summary_line(plan, dry_run=False) + "\n")
        else:
            out.write(summary + "\n")
        return PipelineOutcome(exit_code=0, log_path=str(log_path))
    finally:
        lock.release()


__all__ = [
    "BackupInfo",
    "HEALTH_TIMEOUT_SECONDS",
    "LOCK_FILENAME",
    "LOCK_POLL_SECONDS",
    "LOCK_TIMEOUT_SECONDS",
    "PREPARE_CLONE_TIMEOUT_SECONDS",
    "PREPARE_FF_TIMEOUT_SECONDS",
    "PipelineOptions",
    "PipelineOutcome",
    "REAPPLY_RUST_PROFILE",
    "REAPPLY_TIMEOUT_SECONDS",
    "RESTART_TIMEOUT_SECONDS",
    "RunnerResult",
    "SUMMARY_GIT_TIMEOUT_SECONDS",
    "SUMMARY_SHORT_LENGTH",
    "SWAP_TIMEOUT_SECONDS",
    "SwapLock",
    "UPDATE_AGREE_TIMEOUT_SECONDS",
    "UpdateAgreement",
    "VERIFY_TIMEOUT_SECONDS",
    "acquire_swap_lock",
    "backup_path_for",
    "classify_update_agreement",
    "count_live_advisory_runners",
    "default_runner",
    "describe_blocker",
    "dev_summary_shas",
    "format_holder",
    "holders_dir_for",
    "is_process_running",
    "lock_path_for",
    "log_path_for",
    "managed_sase_exe",
    "missing_plugin_names",
    "quick_health_ok",
    "read_writer_holder",
    "run_dev_pipeline",
    "run_pypi_pipeline",
    "scheduler_running",
    "scrubbed_env",
    "swap_argv_for",
    "tool_python_for",
    "verify_dev_install",
    "verify_pypi_install",
    "write_backup",
]
