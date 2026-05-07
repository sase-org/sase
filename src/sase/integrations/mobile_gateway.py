"""Python lifecycle glue for the SASE mobile gateway."""

from __future__ import annotations

import argparse
import ipaddress
import json
import shlex
import shutil
import subprocess
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.error import URLError
from urllib.request import Request, urlopen

from sase.config.core import load_merged_config

DEFAULT_BIND_ADDRESS = "127.0.0.1"
DEFAULT_PORT = 7629
DEFAULT_STARTUP_TIMEOUT_SECONDS = 10.0


class _MobileGatewayError(RuntimeError):
    """User-facing mobile gateway startup error."""


@dataclass(frozen=True)
class _MobileGatewayConfig:
    bind_address: str = DEFAULT_BIND_ADDRESS
    port: int = DEFAULT_PORT
    state_dir: Path | None = None
    allow_non_loopback: bool = False
    command: tuple[str, ...] = ()
    agent_bridge_command: tuple[str, ...] = ()
    helper_bridge_command: tuple[str, ...] = ()
    push_provider: str = "disabled"
    fcm_project_id: str = ""
    fcm_service_account_json: Path | None = None
    fcm_credential_env: str = ""
    fcm_dry_run: bool = False
    push_timeout_seconds: float = 5.0
    push_retry_limit: int = 1
    startup_timeout_seconds: float = DEFAULT_STARTUP_TIMEOUT_SECONDS


@dataclass(frozen=True)
class _MobileGatewayLaunch:
    argv: list[str]
    bind_address: str
    port: int
    url: str


UrlOpen = Callable[..., Any]
PopenFactory = Callable[..., subprocess.Popen[Any]]
SleepFn = Callable[[float], None]


def _load_mobile_gateway_config() -> _MobileGatewayConfig:
    """Read and normalize the ``mobile_gateway`` merged-config section."""
    raw = load_merged_config().get("mobile_gateway", {})
    if not isinstance(raw, dict):
        raw = {}

    return _MobileGatewayConfig(
        bind_address=_string_value(raw.get("bind_address"), DEFAULT_BIND_ADDRESS),
        port=_port_value(raw.get("port"), DEFAULT_PORT),
        state_dir=_optional_path(raw.get("state_dir")),
        allow_non_loopback=bool(raw.get("allow_non_loopback", False)),
        command=_command_value(raw.get("command")),
        agent_bridge_command=_command_value(raw.get("agent_bridge_command")),
        helper_bridge_command=_command_value(raw.get("helper_bridge_command")),
        push_provider=_push_provider_value(raw.get("push_provider")),
        fcm_project_id=_string_value(raw.get("fcm_project_id"), ""),
        fcm_service_account_json=_optional_path(raw.get("fcm_service_account_json")),
        fcm_credential_env=_string_value(raw.get("fcm_credential_env"), ""),
        fcm_dry_run=bool(raw.get("fcm_dry_run", False)),
        push_timeout_seconds=_positive_float(raw.get("push_timeout_seconds"), 5.0),
        push_retry_limit=_non_negative_int(raw.get("push_retry_limit"), 1),
        startup_timeout_seconds=_positive_float(
            raw.get("startup_timeout_seconds"), DEFAULT_STARTUP_TIMEOUT_SECONDS
        ),
    )


def _prepare_mobile_gateway_launch(
    args: argparse.Namespace,
    *,
    config: _MobileGatewayConfig | None = None,
) -> _MobileGatewayLaunch:
    """Merge CLI/config values and build the safe gateway subprocess argv."""
    config = config or _load_mobile_gateway_config()
    bind_address = _string_value(
        getattr(args, "bind_address", None), config.bind_address
    )
    port = _port_value(getattr(args, "port", None), config.port)
    state_dir = _optional_path(getattr(args, "state_dir", None)) or config.state_dir
    allow_non_loopback = config.allow_non_loopback or bool(
        getattr(args, "allow_non_loopback", False)
    )
    command = _command_value(getattr(args, "gateway_command", None)) or config.command
    agent_bridge_command = (
        _command_value(getattr(args, "agent_bridge_command", None))
        or config.agent_bridge_command
    )
    helper_bridge_command = (
        _command_value(getattr(args, "helper_bridge_command", None))
        or config.helper_bridge_command
    )
    push_provider = _push_provider_value(
        getattr(args, "push_provider", None) or config.push_provider
    )
    fcm_project_id = _string_value(
        getattr(args, "fcm_project_id", None), config.fcm_project_id
    )
    fcm_service_account_json = (
        _optional_path(getattr(args, "fcm_service_account_json", None))
        or config.fcm_service_account_json
    )
    fcm_credential_env = _string_value(
        getattr(args, "fcm_credential_env", None), config.fcm_credential_env
    )
    fcm_dry_run = config.fcm_dry_run or bool(getattr(args, "fcm_dry_run", False))
    push_timeout_seconds = _positive_float(
        getattr(args, "push_timeout_seconds", None), config.push_timeout_seconds
    )
    push_retry_limit = _non_negative_int(
        getattr(args, "push_retry_limit", None), config.push_retry_limit
    )
    if not command:
        command = _resolve_gateway_command()
    if not command:
        raise _MobileGatewayError(
            "mobile gateway binary not found; set mobile_gateway.command "
            "in SASE config or pass --command/-c"
        )

    if not allow_non_loopback and not _is_loopback_host(bind_address):
        raise _MobileGatewayError(
            f"refusing to bind mobile gateway on non-loopback address {bind_address}; "
            "pass --allow-non-loopback/-L only for explicit LAN or tailnet exposure"
        )

    argv = [*command, "--bind", f"{bind_address}:{port}"]
    if state_dir is not None:
        argv.extend(["--sase-home", str(state_dir)])
    if agent_bridge_command:
        argv.extend(["--agent-bridge-command", shlex.join(agent_bridge_command)])
    if helper_bridge_command:
        argv.extend(["--helper-bridge-command", shlex.join(helper_bridge_command)])
    if push_provider != "disabled":
        argv.extend(["--push-provider", push_provider])
    if fcm_project_id:
        argv.extend(["--fcm-project-id", fcm_project_id])
    if fcm_service_account_json is not None:
        argv.extend(["--fcm-service-account-json", str(fcm_service_account_json)])
    if fcm_credential_env:
        argv.extend(["--fcm-credential-env", fcm_credential_env])
    if fcm_dry_run:
        argv.append("--fcm-dry-run")
    if push_timeout_seconds != 5.0:
        argv.extend(["--push-timeout-seconds", f"{push_timeout_seconds:g}"])
    if push_retry_limit != 1:
        argv.extend(["--push-retry-limit", str(push_retry_limit)])
    if allow_non_loopback:
        argv.append("--allow-non-loopback")

    return _MobileGatewayLaunch(
        argv=argv,
        bind_address=bind_address,
        port=port,
        url=_local_probe_url(bind_address, port),
    )


def _run_mobile_gateway_start(
    args: argparse.Namespace,
    *,
    popen: PopenFactory = subprocess.Popen,
    opener: UrlOpen = urlopen,
    sleep: SleepFn = time.sleep,
) -> int:
    """Start the Rust gateway in the foreground and print pairing details."""
    config = _load_mobile_gateway_config()
    launch = _prepare_mobile_gateway_launch(args, config=config)
    startup_timeout = _positive_float(
        getattr(args, "startup_timeout", None), config.startup_timeout_seconds
    )

    print(f"Starting SASE mobile gateway at {launch.url}")
    proc = popen(launch.argv)
    try:
        pairing = _wait_for_pairing(launch.url, proc, startup_timeout, opener, sleep)
        print(f"Pairing code: {pairing['code']}")
        print(f"Pairing ID: {pairing['pairing_id']}")
        print(f"Expires at: {pairing['expires_at']}")
        print("Keep this process running while mobile clients connect.")
        return int(proc.wait())
    except KeyboardInterrupt:
        _terminate_process(proc)
        return 130
    except _MobileGatewayError:
        _terminate_process(proc)
        raise


def handle_mobile_gateway_start(args: argparse.Namespace) -> None:
    """CLI wrapper for ``sase mobile gateway start``."""
    try:
        code = _run_mobile_gateway_start(args)
    except _MobileGatewayError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)
    sys.exit(code)


def _wait_for_pairing(
    base_url: str,
    proc: subprocess.Popen[Any],
    startup_timeout: float,
    opener: UrlOpen,
    sleep: SleepFn,
) -> dict[str, Any]:
    deadline = time.monotonic() + startup_timeout
    last_error: str | None = None
    while time.monotonic() < deadline:
        exit_code = proc.poll()
        if exit_code is not None:
            raise _MobileGatewayError(
                f"mobile gateway exited before startup completed with code {exit_code}"
            )
        try:
            health = _request_json(opener, "GET", f"{base_url}/api/v1/health")
            if health.get("status") == "ok":
                return _request_json(
                    opener,
                    "POST",
                    f"{base_url}/api/v1/session/pair/start",
                    {"schema_version": 1},
                )
        except (OSError, URLError, TimeoutError, json.JSONDecodeError) as exc:
            last_error = str(exc)
        sleep(0.1)
    suffix = f": {last_error}" if last_error else ""
    raise _MobileGatewayError(
        f"mobile gateway did not become ready within {startup_timeout:g}s{suffix}"
    )


def _request_json(
    opener: UrlOpen,
    method: str,
    url: str,
    body: dict[str, Any] | None = None,
) -> dict[str, Any]:
    data = None
    headers: dict[str, str] = {}
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    request = Request(url, data=data, headers=headers, method=method)
    with opener(request, timeout=0.5) as response:
        payload = json.loads(response.read().decode("utf-8"))
    if not isinstance(payload, dict):
        raise _MobileGatewayError(f"gateway returned non-object JSON from {url}")
    return payload


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


def _string_value(value: Any, default: str) -> str:
    if isinstance(value, str) and value.strip():
        return value.strip()
    return default


def _optional_path(value: Any) -> Path | None:
    if isinstance(value, Path):
        return value.expanduser()
    if isinstance(value, str) and value.strip():
        return Path(value).expanduser()
    return None


def _port_value(value: Any, default: int) -> int:
    try:
        port = int(value)
    except (TypeError, ValueError):
        port = default
    if port < 0 or port > 65535:
        raise _MobileGatewayError(f"mobile gateway port out of range: {port}")
    return port


def _positive_float(value: Any, default: float) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return default
    if result <= 0:
        return default
    return result


def _non_negative_int(value: Any, default: int) -> int:
    try:
        result = int(value)
    except (TypeError, ValueError):
        return default
    if result < 0:
        return default
    return result


def _push_provider_value(value: Any) -> str:
    if isinstance(value, str):
        normalized = value.strip().lower().replace("-", "_")
        if normalized in {"disabled", "test", "fcm"}:
            return normalized
    return "disabled"


def _command_value(value: Any) -> tuple[str, ...]:
    if isinstance(value, str):
        return tuple(shlex.split(value)) if value.strip() else ()
    if isinstance(value, (list, tuple)):
        parts = [str(part) for part in value if str(part).strip()]
        return tuple(parts)
    return ()


def _is_loopback_host(host: str) -> bool:
    if host.lower() == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def _local_probe_url(bind_address: str, port: int) -> str:
    host = bind_address
    if host == "0.0.0.0":
        host = "127.0.0.1"
    elif host == "::":
        host = "::1"
    if ":" in host and not host.startswith("["):
        host = f"[{host}]"
    return f"http://{host}:{port}"
