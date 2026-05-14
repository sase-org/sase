"""Python lifecycle glue for the local SASE daemon."""

from __future__ import annotations

import argparse
import json
import os
import shlex
import shutil
import signal
import subprocess
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sase.config.core import load_merged_config

LOCK_METADATA_FILENAME = "daemon.lock.json"
SOCKET_FILENAME = "sase-daemon.sock"
LOCK_SCHEMA_VERSION = 1
DEFAULT_STARTUP_TIMEOUT_SECONDS = 5.0
DEFAULT_STOP_TIMEOUT_SECONDS = 5.0


class _DaemonLifecycleError(RuntimeError):
    """User-facing daemon lifecycle error."""


@dataclass(frozen=True)
class _DaemonLifecycleConfig:
    command: tuple[str, ...] = ()
    sase_home: Path | None = None
    run_root: Path | None = None
    socket_path: Path | None = None
    disable_mobile_http: bool = False
    startup_timeout_seconds: float = DEFAULT_STARTUP_TIMEOUT_SECONDS


@dataclass(frozen=True)
class _DaemonRuntimePaths:
    sase_home: Path
    run_root: Path
    socket_path: Path
    metadata_path: Path


@dataclass(frozen=True)
class _DaemonLaunch:
    argv: list[str]
    paths: _DaemonRuntimePaths
    foreground: bool
    startup_timeout_seconds: float


@dataclass(frozen=True)
class _DaemonInspection:
    state: str
    paths: _DaemonRuntimePaths
    metadata: dict[str, Any] | None = None
    message: str = ""
    rpc: dict[str, Any] | None = None

    @property
    def log_path(self) -> Path:
        return self.paths.run_root / "daemon.log"

    @property
    def metrics_endpoint(self) -> str | None:
        rpc = self.rpc or {}
        health = rpc.get("health") if isinstance(rpc, dict) else None
        if not isinstance(health, dict):
            return None
        details = health.get("details")
        if not isinstance(details, dict):
            return None
        metrics = details.get("metrics")
        if not isinstance(metrics, dict):
            return None
        endpoint = metrics.get("endpoint")
        return endpoint if isinstance(endpoint, str) and endpoint else None


PopenFactory = Callable[..., subprocess.Popen[Any]]
SleepFn = Callable[[float], None]
KillFn = Callable[[int, int], None]


def handle_daemon_start(args: argparse.Namespace) -> int:
    """CLI wrapper for ``sase daemon start``."""
    try:
        return _run_daemon_start(args)
    except _DaemonLifecycleError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


def handle_daemon_status(args: argparse.Namespace) -> int:
    """CLI wrapper for ``sase daemon status``."""
    inspection = _inspect_daemon(args)
    if getattr(args, "json_output", False):
        print(json.dumps(_inspection_to_dict(inspection), indent=2, sort_keys=True))
    else:
        _print_status(inspection)
    return 0


def handle_daemon_stop(args: argparse.Namespace) -> int:
    """CLI wrapper for ``sase daemon stop``."""
    try:
        return _run_daemon_stop(args)
    except _DaemonLifecycleError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


def handle_daemon_doctor(args: argparse.Namespace) -> int:
    """Run daemon lifecycle and projection diagnostics."""
    inspection = _inspect_daemon(args)
    payload = _doctor_payload(inspection)
    if getattr(args, "json_output", False):
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        _print_status(inspection)
        print(f"Doctor: {payload['doctor']['state']}")
        for check in payload["doctor"]["checks"]:
            print(f"- {check['name']}: {check['state']} - {check['message']}")
    return 0


def handle_daemon_rebuild(args: argparse.Namespace) -> int:
    """Rebuild daemon projections through a live daemon or one-shot Rust path."""
    try:
        payload = _run_daemon_rebuild(args)
    except _DaemonLifecycleError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    if getattr(args, "json_output", False):
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        mode = payload.get("mode", "projection_storage_rebuild")
        limitation = payload.get("limitation")
        source = payload.get("source")
        print(f"Rebuild: {mode} completed via {source}.")
        if limitation:
            print(f"Limitation: {limitation}")
    return 0


def _load_daemon_config() -> _DaemonLifecycleConfig:
    raw = load_merged_config().get("daemon", {})
    if not isinstance(raw, dict):
        raw = {}
    return _DaemonLifecycleConfig(
        command=_command_value(raw.get("command")),
        sase_home=_optional_path(raw.get("sase_home")),
        run_root=_optional_path(raw.get("run_root")),
        socket_path=_optional_path(raw.get("socket_path")),
        disable_mobile_http=bool(raw.get("disable_mobile_http", False)),
        startup_timeout_seconds=_positive_float(
            raw.get("startup_timeout_seconds"),
            DEFAULT_STARTUP_TIMEOUT_SECONDS,
        ),
    )


def _prepare_daemon_launch(
    args: argparse.Namespace,
    *,
    config: _DaemonLifecycleConfig | None = None,
) -> _DaemonLaunch:
    """Merge CLI/config values and build the safe gateway daemon argv."""
    config = config or _load_daemon_config()
    command = _command_value(getattr(args, "daemon_command", None)) or config.command
    if not command:
        command = _resolve_gateway_command()
    if not command:
        raise _DaemonLifecycleError(
            "sase_gateway binary not found; set daemon.command in SASE config "
            "or pass --command/-c"
        )

    paths = _runtime_paths_from_args(args, config=config)
    foreground = bool(getattr(args, "foreground", False))
    disable_mobile_http = config.disable_mobile_http or bool(
        getattr(args, "disable_mobile_http", False)
    )
    startup_timeout = _positive_float(
        getattr(args, "startup_timeout", None),
        config.startup_timeout_seconds,
    )

    argv = [*command, "daemon", "--sase-home", str(paths.sase_home)]
    if _arg_path(args, "run_root") is not None or config.run_root is not None:
        argv.extend(["--run-root", str(paths.run_root)])
    if _arg_path(args, "socket_path") is not None or config.socket_path is not None:
        argv.extend(["--socket-path", str(paths.socket_path)])
    if foreground:
        argv.append("--foreground")
    if bool(getattr(args, "tokio_console", False)):
        argv.append("--tokio-console")
    if disable_mobile_http:
        argv.append("--disable-mobile-http")
    if bind_address := getattr(args, "bind_address", None):
        argv.extend(["--bind", str(bind_address)])
    if bool(getattr(args, "allow_non_loopback", False)):
        argv.append("--allow-non-loopback")
    if agent_bridge_command := _command_value(
        getattr(args, "agent_bridge_command", None)
    ):
        argv.extend(["--agent-bridge-command", shlex.join(agent_bridge_command)])
    if helper_bridge_command := _command_value(
        getattr(args, "helper_bridge_command", None)
    ):
        argv.extend(["--helper-bridge-command", shlex.join(helper_bridge_command)])

    return _DaemonLaunch(
        argv=argv,
        paths=paths,
        foreground=foreground,
        startup_timeout_seconds=startup_timeout,
    )


def _runtime_paths_from_args(
    args: argparse.Namespace,
    *,
    config: _DaemonLifecycleConfig | None = None,
) -> _DaemonRuntimePaths:
    """Resolve daemon runtime paths using the same defaults as ``sase_gateway``."""
    config = config or _load_daemon_config()
    sase_home = (
        _arg_path(args, "sase_home")
        or config.sase_home
        or Path(os.environ.get("SASE_HOME") or Path.home() / ".sase")
    ).expanduser()
    run_root = (
        _arg_path(args, "run_root")
        or config.run_root
        or _default_run_root(sase_home, _host_identity_from_env())
    ).expanduser()
    socket_path = (
        _arg_path(args, "socket_path")
        or config.socket_path
        or _default_socket_path(run_root)
    ).expanduser()
    return _DaemonRuntimePaths(
        sase_home=sase_home,
        run_root=run_root,
        socket_path=socket_path,
        metadata_path=run_root / LOCK_METADATA_FILENAME,
    )


def _default_run_root(sase_home: Path, host_identity: str) -> Path:
    return sase_home / "run" / _sanitize_host_identity(host_identity)


def _default_socket_path(run_root: Path) -> Path:
    return run_root / SOCKET_FILENAME


def _host_identity_from_env() -> str:
    value = os.environ.get("HOSTNAME")
    return _sanitize_host_identity(value) if value and value.strip() else "sase-host"


def _sanitize_host_identity(value: str) -> str:
    sanitized = "".join(
        ch if ch.isascii() and (ch.isalnum() or ch in ".-_") else "-"
        for ch in value.strip()
    ).strip("-")
    return sanitized or "sase-host"


def _inspect_daemon(args: argparse.Namespace) -> _DaemonInspection:
    """Inspect daemon metadata first, then optional local health RPC."""
    paths = _runtime_paths_from_args(args)
    metadata_result = _read_metadata(paths.metadata_path)
    if metadata_result is None:
        return _DaemonInspection(
            state="stopped",
            paths=paths,
            message=f"no ownership metadata at {paths.metadata_path}",
        )
    if isinstance(metadata_result, str):
        return _DaemonInspection(
            state="incompatible",
            paths=paths,
            message=metadata_result,
        )

    metadata = metadata_result
    schema_version = _int_value(metadata.get("schema_version"))
    if schema_version != LOCK_SCHEMA_VERSION:
        return _DaemonInspection(
            state="incompatible",
            paths=paths,
            metadata=metadata,
            message=f"unsupported lock metadata schema {schema_version}",
        )

    current_host = _host_identity_from_env()
    metadata_host = str(metadata.get("hostname") or "")
    if metadata_host != current_host:
        return _DaemonInspection(
            state="conflict",
            paths=paths,
            metadata=metadata,
            message=(
                f"metadata belongs to host {metadata_host!r}, "
                f"not this host {current_host!r}"
            ),
        )

    pid = _int_value(metadata.get("pid"))
    if pid is None or not _process_is_live(pid):
        return _DaemonInspection(
            state="stale",
            paths=paths,
            metadata=metadata,
            message=f"metadata pid {pid!r} is not live",
        )

    rpc = _try_health_rpc(paths.socket_path)
    return _DaemonInspection(
        state="running",
        paths=paths,
        metadata=metadata,
        rpc=rpc,
        message=f"daemon metadata points at live pid {pid}",
    )


def _run_daemon_start(
    args: argparse.Namespace,
    *,
    popen: PopenFactory = subprocess.Popen,
    sleep: SleepFn = time.sleep,
) -> int:
    launch = _prepare_daemon_launch(args)
    if launch.foreground:
        print("Starting SASE daemon in the foreground.")
        proc = popen(launch.argv)
        try:
            return int(proc.wait())
        except KeyboardInterrupt:
            _terminate_process(proc)
            return 130

    launch.paths.run_root.mkdir(parents=True, exist_ok=True)
    log_path = launch.paths.run_root / "daemon.log"
    print(f"Starting SASE daemon in the background. Log: {log_path}")
    with open(log_path, "ab") as log_file:
        proc = popen(
            launch.argv,
            stdout=log_file,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
    inspection = _wait_for_background_start(launch, proc, sleep)
    if inspection.state == "running":
        if inspection.rpc and inspection.rpc.get("available"):
            print("SASE daemon started; local RPC health is available.")
        else:
            print(
                "SASE daemon started; ownership metadata is available. "
                "Local RPC health is unavailable until the daemon transport is ready."
            )
        return 0
    raise _DaemonLifecycleError(inspection.message)


def _run_daemon_stop(
    args: argparse.Namespace,
    *,
    kill: KillFn = os.kill,
    sleep: SleepFn = time.sleep,
) -> int:
    inspection = _inspect_daemon(args)
    if inspection.state == "stopped":
        print("SASE daemon is not running.")
        return 0
    if inspection.state != "running" or inspection.metadata is None:
        raise _DaemonLifecycleError(
            f"refusing to stop daemon from {inspection.state} metadata: "
            f"{inspection.message}"
        )

    pid = _int_value(inspection.metadata.get("pid"))
    if pid is None:
        raise _DaemonLifecycleError("refusing to stop daemon with missing pid")
    if not _executable_matches_metadata(pid, inspection.metadata):
        raise _DaemonLifecycleError(
            f"refusing to signal pid {pid}; executable does not match metadata"
        )

    kill(pid, signal.SIGTERM)
    timeout = _positive_float(
        getattr(args, "stop_timeout", None),
        DEFAULT_STOP_TIMEOUT_SECONDS,
    )
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not _process_is_live(pid):
            print(f"Stopped SASE daemon pid {pid}.")
            return 0
        sleep(0.1)
    raise _DaemonLifecycleError(
        f"sent SIGTERM to daemon pid {pid}, but it is still running"
    )


def _run_daemon_rebuild(args: argparse.Namespace) -> dict[str, Any]:
    inspection = _inspect_daemon(args)
    timeout = _positive_float(getattr(args, "rebuild_timeout", None), 5.0)
    if inspection.state == "running" and inspection.rpc is not None:
        if inspection.rpc.get("available"):
            try:
                from sase.daemon.client import LocalDaemonClient

                payload = LocalDaemonClient(
                    inspection.paths.socket_path,
                    timeout=timeout,
                ).rebuild(storage_reset_only=True)
            except Exception as exc:
                raise _DaemonLifecycleError(
                    f"live daemon rebuild RPC failed: {exc}"
                ) from exc
            payload["source"] = "live_daemon_rpc"
            return payload
        raise _DaemonLifecycleError(
            "daemon metadata is live but local RPC is unavailable; run "
            "`sase daemon doctor` before rebuilding"
        )
    if inspection.state not in {"stopped", "stale"}:
        raise _DaemonLifecycleError(
            f"refusing one-shot rebuild from {inspection.state} daemon state: "
            f"{inspection.message}"
        )

    launch = _prepare_daemon_launch(
        argparse.Namespace(
            **{
                **vars(args),
                "foreground": False,
                "disable_mobile_http": True,
                "tokio_console": False,
            }
        )
    )
    argv = [*launch.argv, "--rebuild-once"]
    result = subprocess.run(  # noqa: S603
        argv,
        check=False,
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    if result.returncode != 0:
        stderr = result.stderr.strip()
        raise _DaemonLifecycleError(
            f"one-shot rebuild failed with code {result.returncode}: {stderr}"
        )
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise _DaemonLifecycleError(
            f"one-shot rebuild returned invalid JSON: {exc}"
        ) from exc
    if not isinstance(payload, dict):
        raise _DaemonLifecycleError("one-shot rebuild returned non-object JSON")
    payload["source"] = "one_shot_daemon_rebuild"
    return payload


def _wait_for_background_start(
    launch: _DaemonLaunch,
    proc: subprocess.Popen[Any],
    sleep: SleepFn,
) -> _DaemonInspection:
    deadline = time.monotonic() + launch.startup_timeout_seconds
    last = _DaemonInspection(
        state="stopped",
        paths=launch.paths,
        message="daemon did not publish ownership metadata yet",
    )
    args = argparse.Namespace(
        sase_home=str(launch.paths.sase_home),
        run_root=str(launch.paths.run_root),
        socket_path=str(launch.paths.socket_path),
    )
    while time.monotonic() < deadline:
        exit_code = proc.poll()
        if exit_code is not None:
            return _DaemonInspection(
                state="stopped",
                paths=launch.paths,
                message=f"daemon exited before startup completed with code {exit_code}",
            )
        last = _inspect_daemon(args)
        if last.state == "running":
            return last
        sleep(0.1)
    return last


def _read_metadata(path: Path) -> dict[str, Any] | str | None:
    try:
        raw = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return None
    except OSError as exc:
        return f"failed to read ownership metadata {path}: {exc}"
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        return f"failed to parse ownership metadata {path}: {exc}"
    if not isinstance(payload, dict):
        return f"ownership metadata {path} is not a JSON object"
    return payload


def _try_health_rpc(socket_path: Path) -> dict[str, Any]:
    if not socket_path.exists():
        return {
            "available": False,
            "message": f"local socket is not available at {socket_path}",
        }
    try:
        from sase.daemon import client as daemon_client  # type: ignore[import-not-found]
    except ImportError:
        return {
            "available": False,
            "message": "Python local daemon client is not available yet",
        }

    try:
        if hasattr(daemon_client, "health"):
            health = daemon_client.health(socket_path=socket_path, timeout=0.5)
        elif hasattr(daemon_client, "LocalDaemonClient"):
            health = daemon_client.LocalDaemonClient(socket_path, timeout=0.5).health()
        else:
            return {
                "available": False,
                "message": "Python local daemon client has no health helper",
            }
    except Exception as exc:
        return {"available": False, "message": str(exc)}
    return {"available": True, "health": health}


def _print_status(inspection: _DaemonInspection) -> None:
    print(f"SASE daemon status: {inspection.state}")
    print(f"Run root: {inspection.paths.run_root}")
    print(f"Socket: {inspection.paths.socket_path}")
    print(f"Log: {inspection.log_path}")
    if inspection.metrics_endpoint:
        print(f"Metrics: {inspection.metrics_endpoint}")
    if inspection.metadata is not None:
        pid = inspection.metadata.get("pid")
        hostname = inspection.metadata.get("hostname")
        started_at = inspection.metadata.get("started_at")
        build = inspection.metadata.get("build_version")
        print(f"PID: {pid}")
        print(f"Host: {hostname}")
        print(f"Started: {started_at}")
        print(f"Build: {build}")
    if inspection.message:
        print(f"Detail: {inspection.message}")
    if inspection.rpc is not None:
        print(f"RPC: {inspection.rpc.get('message') or inspection.rpc}")


def _inspection_to_dict(inspection: _DaemonInspection) -> dict[str, Any]:
    return {
        "state": inspection.state,
        "sase_home": str(inspection.paths.sase_home),
        "run_root": str(inspection.paths.run_root),
        "socket_path": str(inspection.paths.socket_path),
        "metadata_path": str(inspection.paths.metadata_path),
        "log_path": str(inspection.log_path),
        "metrics_endpoint": inspection.metrics_endpoint,
        "metadata": inspection.metadata,
        "message": inspection.message,
        "rpc": inspection.rpc,
    }


def _doctor_payload(inspection: _DaemonInspection) -> dict[str, Any]:
    checks = [
        _check(
            "lock_metadata",
            _metadata_check_state(inspection),
            inspection.message or "ownership metadata parsed",
        ),
        _check(
            "process_liveness",
            "ok" if inspection.state == "running" else inspection.state,
            _process_check_message(inspection),
        ),
        _check(
            "socket_rpc_health",
            _rpc_check_state(inspection),
            _rpc_check_message(inspection),
        ),
        _check(
            "projection_db",
            _projection_check_state(inspection),
            _projection_check_message(inspection),
        ),
        _check(
            "mobile_http",
            _mobile_http_check_state(inspection),
            _mobile_http_check_message(inspection),
        ),
    ]
    doctor_state = _worst_check_state(check["state"] for check in checks)
    payload = _inspection_to_dict(inspection)
    payload["doctor"] = {"state": doctor_state, "checks": checks}
    return payload


def _check(name: str, state: str, message: str) -> dict[str, str]:
    return {"name": name, "state": state, "message": message}


def _metadata_check_state(inspection: _DaemonInspection) -> str:
    if inspection.state in {"running", "stale", "stopped"}:
        return inspection.state if inspection.state != "running" else "ok"
    return "error"


def _process_check_message(inspection: _DaemonInspection) -> str:
    if inspection.state == "running":
        pid = (inspection.metadata or {}).get("pid")
        return f"metadata pid {pid} is live"
    return inspection.message or f"daemon is {inspection.state}"


def _rpc_check_state(inspection: _DaemonInspection) -> str:
    if inspection.state != "running":
        return "skipped"
    if not inspection.rpc or not inspection.rpc.get("available"):
        return "error"
    health = inspection.rpc.get("health")
    if isinstance(health, dict) and health.get("status") == "degraded":
        return "degraded"
    return "ok"


def _rpc_check_message(inspection: _DaemonInspection) -> str:
    if inspection.state != "running":
        return "daemon is not running"
    if not inspection.rpc:
        return "local RPC was not checked"
    if not inspection.rpc.get("available"):
        return str(inspection.rpc.get("message") or "local RPC unavailable")
    health = inspection.rpc.get("health")
    if isinstance(health, dict):
        return f"health status {health.get('status', 'unknown')}"
    return "local RPC health is available"


def _projection_check_state(inspection: _DaemonInspection) -> str:
    projection = _projection_details(inspection)
    if projection is None:
        return "skipped" if inspection.state != "running" else "unknown"
    state = projection.get("state")
    if state == "ok":
        return "ok"
    if state == "degraded":
        return "degraded"
    return "unknown"


def _projection_check_message(inspection: _DaemonInspection) -> str:
    projection = _projection_details(inspection)
    if projection is None:
        return "projection health requires live daemon RPC"
    message = projection.get("message")
    if isinstance(message, str) and message:
        return message
    return (
        "schema_initialized={schema_initialized}, migrations_applied={migrations}, "
        "repair_needed={repair_needed}, gaps={gap_count}, recovery_issues={issues}"
    ).format(
        schema_initialized=projection.get("schema_initialized"),
        migrations=projection.get("migrations_applied"),
        repair_needed=projection.get("repair_needed"),
        gap_count=projection.get("gap_count"),
        issues=projection.get("recovery_issue_count"),
    )


def _projection_details(inspection: _DaemonInspection) -> dict[str, Any] | None:
    rpc = inspection.rpc or {}
    health = rpc.get("health") if isinstance(rpc, dict) else None
    details = health.get("details") if isinstance(health, dict) else None
    projection = details.get("projection_db") if isinstance(details, dict) else None
    return projection if isinstance(projection, dict) else None


def _mobile_http_check_state(inspection: _DaemonInspection) -> str:
    if inspection.state != "running":
        return "skipped"
    return "ok" if inspection.metrics_endpoint else "skipped"


def _mobile_http_check_message(inspection: _DaemonInspection) -> str:
    if inspection.state != "running":
        return "daemon is not running"
    if inspection.metrics_endpoint:
        return f"loopback metrics endpoint: {inspection.metrics_endpoint}"
    return "mobile HTTP is disabled or metrics endpoint was not published"


def _worst_check_state(states: Any) -> str:
    order = {
        "error": 5,
        "conflict": 5,
        "incompatible": 5,
        "degraded": 4,
        "stale": 3,
        "unknown": 2,
        "skipped": 1,
        "stopped": 1,
        "ok": 0,
    }
    worst = "ok"
    worst_score = 0
    for state in states:
        score = order.get(str(state), 2)
        if score > worst_score:
            worst = str(state)
            worst_score = score
    return worst


def _resolve_gateway_command() -> tuple[str, ...]:
    path = shutil.which("sase_gateway")
    if path:
        return (path,)

    repo_root = Path(__file__).resolve().parents[3]
    sibling_core = repo_root.parent / "sase-core"
    for candidate in (
        sibling_core / "target" / "debug" / "sase_gateway",
        sibling_core / "target" / "release" / "sase_gateway",
    ):
        if candidate.is_file():
            return (str(candidate),)
    return ()


def _terminate_process(proc: subprocess.Popen[Any]) -> None:
    if proc.poll() is not None:
        return
    proc.terminate()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait()


def _process_is_live(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except (OverflowError, ProcessLookupError):
        return False
    except PermissionError:
        return True
    return True


def _executable_matches_metadata(pid: int, metadata: dict[str, Any]) -> bool:
    expected_raw = metadata.get("executable_path")
    if not isinstance(expected_raw, str) or not expected_raw:
        return True
    proc_exe = Path("/proc") / str(pid) / "exe"
    if not proc_exe.exists():
        return True
    try:
        actual = proc_exe.resolve(strict=True)
        expected = Path(expected_raw).expanduser().resolve(strict=False)
    except OSError:
        return True
    return actual == expected


def _arg_path(args: argparse.Namespace, name: str) -> Path | None:
    return _optional_path(getattr(args, name, None))


def _optional_path(value: Any) -> Path | None:
    if isinstance(value, Path):
        return value.expanduser()
    if isinstance(value, str) and value.strip():
        return Path(value).expanduser()
    return None


def _command_value(value: Any) -> tuple[str, ...]:
    if isinstance(value, str):
        return tuple(shlex.split(value)) if value.strip() else ()
    if isinstance(value, (list, tuple)):
        return tuple(str(part) for part in value if str(part).strip())
    return ()


def _positive_float(value: Any, default: float) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return default
    if result <= 0:
        return default
    return result


def _int_value(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
