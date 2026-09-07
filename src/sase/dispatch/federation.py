"""Python facade and supervisor for the local federation worker."""

from __future__ import annotations

import asyncio
import json
import os
import shlex
import shutil
import socket
import struct
import subprocess
import threading
import time
import uuid
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from sase.config.core import load_merged_config
from sase.core.paths import sase_home
from sase.core.rust import require_rust_binding

FEDERATION_IPC_SCHEMA_VERSION = 1
FEDERATION_MAX_FRAME_BYTES = 1024 * 1024
FEDERATION_WORKER_COMMAND = "sase_federation_worker"
FEDERATION_WORKER_SOCKET = "sase-federation-worker.sock"


class FederationConfigError(RuntimeError):
    """Raised when configured federation hosts cannot be projected safely."""


class FederationWorkerUnavailable(RuntimeError):
    """Raised when the local federation worker cannot be reached or started."""


class FederationWorkerResponseError(RuntimeError):
    """Raised when the worker returns an IPC-level error response."""

    def __init__(self, error: Mapping[str, Any]) -> None:
        self.error = dict(error)
        message = str(self.error.get("message") or "federation worker request failed")
        super().__init__(message)


@dataclass(frozen=True)
class FederationWorkerSettings:
    """Resolved non-secret worker supervision settings."""

    enabled: bool = True
    command: tuple[str, ...] = ()
    sase_home: Path = field(default_factory=sase_home)
    run_root: Path | None = None
    socket_path: Path | None = None
    idle_timeout_seconds: float = 300.0
    startup_timeout_seconds: float = 5.0
    request_timeout_seconds: float = 5.0
    max_frame_bytes: int = FEDERATION_MAX_FRAME_BYTES

    @property
    def resolved_run_root(self) -> Path:
        return self.run_root or self.sase_home / "run" / _host_identity()

    @property
    def resolved_socket_path(self) -> Path:
        return self.socket_path or self.resolved_run_root / FEDERATION_WORKER_SOCKET


@dataclass(frozen=True)
class FederationHostConfig:
    """One remote fleet host plus its resolved bearer token."""

    alias: str | None
    plan: dict[str, Any]
    bearer_token: str

    def to_wire(self) -> dict[str, Any]:
        return {
            "schema_version": FEDERATION_IPC_SCHEMA_VERSION,
            "alias": self.alias,
            "plan": dict(self.plan),
            "bearer_token": self.bearer_token,
        }

    def redacted(self) -> dict[str, Any]:
        payload = self.to_wire()
        payload["bearer_token"] = "<redacted>"
        return payload


@dataclass(frozen=True)
class FederationConfig:
    """Resolved federation facade configuration."""

    worker: FederationWorkerSettings
    hosts: tuple[FederationHostConfig, ...] = ()

    @property
    def enabled(self) -> bool:
        return self.worker.enabled and bool(self.hosts)

    def hosts_wire(self) -> list[dict[str, Any]]:
        return [host.to_wire() for host in self.hosts]

    def redacted_hosts(self) -> list[dict[str, Any]]:
        return [host.redacted() for host in self.hosts]


IpcClientFactory = Callable[[Path, int], "FederationIpcClient"]
PopenFactory = Callable[..., subprocess.Popen[Any]]
SleepFn = Callable[[float], None]
MonotonicFn = Callable[[], float]


def load_federation_config(
    raw_config: Mapping[str, Any] | None = None,
) -> FederationConfig:
    """Read and validate ``dispatch`` federation configuration."""

    config = raw_config if raw_config is not None else load_merged_config()
    dispatch = _mapping(config.get("dispatch"))
    worker = _worker_settings(_mapping(dispatch.get("federation_worker")))
    raw_hosts = dispatch.get("remote_hosts")
    if not isinstance(raw_hosts, list):
        raw_hosts = []
    hosts: list[FederationHostConfig] = []
    for index, raw_host in enumerate(raw_hosts):
        if not isinstance(raw_host, Mapping):
            raise FederationConfigError(
                f"dispatch.remote_hosts[{index}] must be an object"
            )
        if raw_host.get("enabled", True) is False:
            continue
        hosts.append(_host_config(raw_host, index))
    return FederationConfig(worker=worker, hosts=tuple(hosts))


def build_federation_facade(
    config: FederationConfig | None = None,
    *,
    supervisor: FederationWorkerSupervisor | None = None,
) -> FederationFacade:
    """Return the remote-fleet facade for the current configuration."""

    config = config or load_federation_config()
    return FederationFacade(config, supervisor=supervisor)


def resolve_federation_worker_command(
    settings: FederationWorkerSettings | None = None,
) -> tuple[str, ...]:
    """Resolve the packaged worker command, then linked-core dev binaries."""

    settings = settings or FederationWorkerSettings()
    if settings.command:
        return settings.command
    packaged = shutil.which(FEDERATION_WORKER_COMMAND)
    if packaged:
        return (packaged,)

    repo_root = Path(__file__).resolve().parents[3]
    candidates = [
        repo_root / "sase/repos/linked/sase-core/target/debug/sase_federation_worker",
        repo_root / "sase/repos/linked/sase-core/target/release/sase_federation_worker",
        repo_root
        / "sase/repos/external/gh/sase-org/sase-core/target/debug/sase_federation_worker",
        repo_root
        / "sase/repos/external/gh/sase-org/sase-core/target/release/sase_federation_worker",
        repo_root.parent / "sase-core/target/debug/sase_federation_worker",
        repo_root.parent / "sase-core/target/release/sase_federation_worker",
    ]
    for candidate in candidates:
        if candidate.is_file():
            return (str(candidate),)
    return ()


@dataclass
class FederationFacade:
    """Async read facade backed by the local worker when hosts are configured."""

    config: FederationConfig
    supervisor: FederationWorkerSupervisor | None = None

    def __post_init__(self) -> None:
        if self.supervisor is None and self.config.enabled:
            self.supervisor = FederationWorkerSupervisor(self.config)

    async def health(self, *, timeout_seconds: float | None = None) -> dict[str, Any]:
        return await asyncio.to_thread(
            self.health_sync, timeout_seconds=timeout_seconds
        )

    async def summary(
        self,
        *,
        cache_only: bool = False,
        timeout_seconds: float | None = None,
    ) -> dict[str, Any]:
        return await asyncio.to_thread(
            self.summary_sync,
            cache_only=cache_only,
            timeout_seconds=timeout_seconds,
        )

    async def catalog(
        self,
        query: Mapping[str, Any],
        *,
        cache_only: bool = False,
        timeout_seconds: float | None = None,
    ) -> dict[str, Any]:
        return await asyncio.to_thread(
            self.catalog_sync,
            query,
            cache_only=cache_only,
            timeout_seconds=timeout_seconds,
        )

    async def followed_batch(
        self,
        request: Mapping[str, Any],
        *,
        cache_only: bool = False,
        timeout_seconds: float | None = None,
    ) -> dict[str, Any]:
        return await asyncio.to_thread(
            self.followed_batch_sync,
            request,
            cache_only=cache_only,
            timeout_seconds=timeout_seconds,
        )

    async def detail(
        self,
        request: Mapping[str, Any],
        *,
        cache_only: bool = False,
        timeout_seconds: float | None = None,
    ) -> dict[str, Any]:
        return await asyncio.to_thread(
            self.detail_sync,
            request,
            cache_only=cache_only,
            timeout_seconds=timeout_seconds,
        )

    async def content_range(
        self,
        request: Mapping[str, Any],
        *,
        cache_only: bool = False,
        timeout_seconds: float | None = None,
    ) -> dict[str, Any]:
        return await asyncio.to_thread(
            self.content_range_sync,
            request,
            cache_only=cache_only,
            timeout_seconds=timeout_seconds,
        )

    async def project_eligibility(
        self,
        request: Mapping[str, Any],
        *,
        cache_only: bool = False,
        timeout_seconds: float | None = None,
    ) -> dict[str, Any]:
        return await asyncio.to_thread(
            self.project_eligibility_sync,
            request,
            cache_only=cache_only,
            timeout_seconds=timeout_seconds,
        )

    def health_sync(self, *, timeout_seconds: float | None = None) -> dict[str, Any]:
        if not self.config.enabled:
            return {
                "schema_version": FEDERATION_IPC_SCHEMA_VERSION,
                "status": "disabled",
                "service": FEDERATION_WORKER_COMMAND,
                "configured_hosts": 0,
                "capabilities": [],
            }
        return self._request({"op": "health"}, timeout_seconds=timeout_seconds)

    def summary_sync(
        self,
        *,
        cache_only: bool = False,
        timeout_seconds: float | None = None,
    ) -> dict[str, Any]:
        return self._read(
            "summary",
            {"op": "summary", "cache_only": cache_only},
            timeout_seconds=timeout_seconds,
        )

    def catalog_sync(
        self,
        query: Mapping[str, Any],
        *,
        cache_only: bool = False,
        timeout_seconds: float | None = None,
    ) -> dict[str, Any]:
        return self._read(
            "catalog",
            {"op": "catalog", "query": dict(query), "cache_only": cache_only},
            timeout_seconds=timeout_seconds,
        )

    def followed_batch_sync(
        self,
        request: Mapping[str, Any],
        *,
        cache_only: bool = False,
        timeout_seconds: float | None = None,
    ) -> dict[str, Any]:
        return self._read(
            "followed_batch",
            {
                "op": "followed_batch",
                "request": dict(request),
                "cache_only": cache_only,
            },
            timeout_seconds=timeout_seconds,
        )

    def detail_sync(
        self,
        request: Mapping[str, Any],
        *,
        cache_only: bool = False,
        timeout_seconds: float | None = None,
    ) -> dict[str, Any]:
        return self._read(
            "detail",
            {"op": "detail", "request": dict(request), "cache_only": cache_only},
            timeout_seconds=timeout_seconds,
        )

    def content_range_sync(
        self,
        request: Mapping[str, Any],
        *,
        cache_only: bool = False,
        timeout_seconds: float | None = None,
    ) -> dict[str, Any]:
        return self._read(
            "content_range",
            {
                "op": "content_range",
                "request": dict(request),
                "cache_only": cache_only,
            },
            timeout_seconds=timeout_seconds,
        )

    def project_eligibility_sync(
        self,
        request: Mapping[str, Any],
        *,
        cache_only: bool = False,
        timeout_seconds: float | None = None,
    ) -> dict[str, Any]:
        return self._read(
            "project_eligibility",
            {
                "op": "project_eligibility",
                "request": dict(request),
                "cache_only": cache_only,
            },
            timeout_seconds=timeout_seconds,
        )

    def shutdown_sync(self, *, timeout_seconds: float | None = None) -> dict[str, Any]:
        if not self.config.enabled:
            return {"schema_version": FEDERATION_IPC_SCHEMA_VERSION, "shutdown": False}
        return self._request(
            {"op": "shutdown"},
            timeout_seconds=timeout_seconds,
            retry=False,
        )

    def _read(
        self,
        operation: str,
        request: Mapping[str, Any],
        *,
        timeout_seconds: float | None,
    ) -> dict[str, Any]:
        if not self.config.enabled:
            return _disabled_read(operation)
        return self._request(request, timeout_seconds=timeout_seconds)

    def _request(
        self,
        operation: Mapping[str, Any],
        *,
        timeout_seconds: float | None,
        retry: bool = True,
    ) -> dict[str, Any]:
        if self.supervisor is None:
            raise FederationWorkerUnavailable(
                "federation worker supervisor is disabled"
            )
        return self.supervisor.request(
            operation,
            timeout_seconds=timeout_seconds,
            retry=retry,
        )


@dataclass
class FederationWorkerSupervisor:
    """Race-safe on-demand worker process supervisor."""

    config: FederationConfig
    command_resolver: Callable[[FederationWorkerSettings], tuple[str, ...]] = (
        resolve_federation_worker_command
    )
    client_factory: IpcClientFactory = lambda path, max_frame_bytes: (
        FederationIpcClient(path, max_frame_bytes)
    )
    popen: PopenFactory = subprocess.Popen
    sleep: SleepFn = time.sleep
    monotonic: MonotonicFn = time.monotonic
    _lock: threading.RLock = field(default_factory=threading.RLock, init=False)
    _proc: subprocess.Popen[Any] | None = field(default=None, init=False)
    _configured: bool = field(default=False, init=False)

    def request(
        self,
        operation: Mapping[str, Any],
        *,
        timeout_seconds: float | None = None,
        retry: bool = True,
    ) -> dict[str, Any]:
        timeout = _timeout(timeout_seconds, self.config.worker.request_timeout_seconds)
        self.ensure_started(timeout)
        try:
            return self._send(operation, timeout)
        except FederationWorkerUnavailable:
            if not retry or operation.get("op") == "shutdown":
                raise
            with self._lock:
                self._configured = False
            self.ensure_started(timeout, force=True)
            return self._send(operation, timeout)

    def ensure_started(self, timeout_seconds: float, *, force: bool = False) -> None:
        if not force and self._healthy(timeout_seconds=0.2):
            self._ensure_configured(timeout_seconds)
            return
        with self._lock:
            if not force and self._healthy(timeout_seconds=0.2):
                self._ensure_configured(timeout_seconds)
                return
            command = self.command_resolver(self.config.worker)
            if not command:
                raise FederationWorkerUnavailable(
                    "federation worker command not found; install sase-core-rs or build "
                    "sase-core with `cargo build -p sase_gateway`"
                )
            argv = self._worker_argv(command)
            self._proc = self.popen(
                argv,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=os.name != "nt",
            )
            self._wait_for_health(timeout_seconds)
            self._ensure_configured(timeout_seconds)

    def _worker_argv(self, command: Sequence[str]) -> list[str]:
        settings = self.config.worker
        argv = [
            *command,
            "--sase-home",
            str(settings.sase_home),
            "--socket",
            str(settings.resolved_socket_path),
            "--idle-timeout-seconds",
            f"{settings.idle_timeout_seconds:g}",
            "--max-frame-bytes",
            str(settings.max_frame_bytes),
        ]
        if settings.run_root is not None:
            argv.extend(["--run-root", str(settings.run_root)])
        return argv

    def _wait_for_health(self, timeout_seconds: float) -> None:
        deadline = self.monotonic() + timeout_seconds
        last_error: Exception | None = None
        while self.monotonic() < deadline:
            if self._proc is not None and self._proc.poll() is not None:
                raise FederationWorkerUnavailable(
                    "federation worker exited before health check completed"
                )
            try:
                health = self._send({"op": "health"}, min(0.5, timeout_seconds))
                if health.get("status") == "ok":
                    return
            except (FederationWorkerUnavailable, FederationWorkerResponseError) as exc:
                last_error = exc
            self.sleep(0.05)
        suffix = f": {last_error}" if last_error else ""
        raise FederationWorkerUnavailable(
            f"federation worker did not become ready within {timeout_seconds:g}s{suffix}"
        )

    def _ensure_configured(self, timeout_seconds: float) -> None:
        with self._lock:
            if self._configured:
                return
            self._send(
                {"op": "replace_config", "hosts": self.config.hosts_wire()},
                timeout_seconds,
            )
            self._configured = True

    def _healthy(self, *, timeout_seconds: float) -> bool:
        try:
            health = self._send({"op": "health"}, timeout_seconds)
        except (FederationWorkerUnavailable, FederationWorkerResponseError):
            return False
        return health.get("status") == "ok"

    def _send(
        self, operation: Mapping[str, Any], timeout_seconds: float
    ) -> dict[str, Any]:
        client = self.client_factory(
            self.config.worker.resolved_socket_path,
            self.config.worker.max_frame_bytes,
        )
        return client.request(operation, timeout_seconds=timeout_seconds)


@dataclass(frozen=True)
class FederationIpcClient:
    """Blocking length-prefixed JSON IPC client."""

    socket_path: Path
    max_frame_bytes: int = FEDERATION_MAX_FRAME_BYTES

    def request(
        self,
        operation: Mapping[str, Any],
        *,
        timeout_seconds: float,
    ) -> dict[str, Any]:
        timeout = _timeout(timeout_seconds, 5.0)
        request_id = f"py-{uuid.uuid4().hex}"
        deadline_unix_ms = int((time.time() + timeout) * 1000)
        envelope = {
            "schema_version": FEDERATION_IPC_SCHEMA_VERSION,
            "request_id": request_id,
            "deadline_unix_ms": deadline_unix_ms,
            "operation": dict(operation),
        }
        try:
            payload = json.dumps(envelope, separators=(",", ":")).encode("utf-8")
        except (TypeError, ValueError) as exc:
            raise FederationWorkerUnavailable(
                "IPC request is not JSON serializable"
            ) from exc
        if len(payload) > self.max_frame_bytes:
            raise FederationWorkerUnavailable("IPC request exceeds frame limit")

        try:
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
                sock.settimeout(timeout)
                sock.connect(str(self.socket_path))
                sock.sendall(struct.pack(">I", len(payload)) + payload)
                response = self._read_frame(sock)
        except OSError as exc:
            raise FederationWorkerUnavailable(
                f"federation worker socket is unavailable: {self.socket_path}"
            ) from exc
        try:
            decoded = json.loads(response.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise FederationWorkerUnavailable(
                "federation worker returned invalid JSON"
            ) from exc
        if not isinstance(decoded, dict):
            raise FederationWorkerUnavailable(
                "federation worker returned non-object JSON"
            )
        if decoded.get("schema_version") != FEDERATION_IPC_SCHEMA_VERSION:
            raise FederationWorkerUnavailable(
                "federation worker returned an unsupported schema version"
            )
        if decoded.get("request_id") != request_id:
            raise FederationWorkerUnavailable(
                "federation worker returned a mismatched request_id"
            )
        if not decoded.get("ok"):
            error = decoded.get("error")
            if not isinstance(error, Mapping):
                error = {"message": "federation worker returned an unknown error"}
            raise FederationWorkerResponseError(error)
        result = decoded.get("result")
        if not isinstance(result, dict):
            raise FederationWorkerUnavailable(
                "federation worker returned no result object"
            )
        return result

    def _read_frame(self, sock: socket.socket) -> bytes:
        header = _recv_exact(sock, 4)
        length = struct.unpack(">I", header)[0]
        if length == 0:
            raise FederationWorkerUnavailable("IPC response frame was empty")
        if length > self.max_frame_bytes:
            raise FederationWorkerUnavailable("IPC response exceeds frame limit")
        return _recv_exact(sock, length)


def _recv_exact(sock: socket.socket, count: int) -> bytes:
    chunks: list[bytes] = []
    remaining = count
    while remaining:
        chunk = sock.recv(remaining)
        if not chunk:
            raise FederationWorkerUnavailable("IPC socket closed mid-frame")
        chunks.append(chunk)
        remaining -= len(chunk)
    return b"".join(chunks)


def _worker_settings(raw: Mapping[str, Any]) -> FederationWorkerSettings:
    sase_home_value = _optional_path(raw.get("sase_home")) or sase_home()
    run_root = _optional_path(raw.get("run_root"))
    socket_path = _optional_path(raw.get("socket_path"))
    return FederationWorkerSettings(
        enabled=bool(raw.get("enabled", True)),
        command=_command_value(raw.get("command")),
        sase_home=sase_home_value,
        run_root=run_root,
        socket_path=socket_path,
        idle_timeout_seconds=_positive_float(raw.get("idle_timeout_seconds"), 300.0),
        startup_timeout_seconds=_positive_float(
            raw.get("startup_timeout_seconds"), 5.0
        ),
        request_timeout_seconds=_positive_float(
            raw.get("request_timeout_seconds"), 5.0
        ),
        max_frame_bytes=_positive_int(
            raw.get("max_frame_bytes"), FEDERATION_MAX_FRAME_BYTES
        ),
    )


def _host_config(raw: Mapping[str, Any], index: int) -> FederationHostConfig:
    plan = _connection_plan(raw)
    validate = require_rust_binding("fleet_validate_connection_plan")
    try:
        validated = validate(plan)
    except Exception as exc:
        raise FederationConfigError(
            f"dispatch.remote_hosts[{index}] has an invalid connection plan: {exc}"
        ) from exc
    if not isinstance(validated, dict):
        raise FederationConfigError(
            f"dispatch.remote_hosts[{index}] validation returned a non-object plan"
        )
    credential_ref = str(validated.get("credential_ref") or "")
    bearer_token = _resolve_credential(credential_ref, index)
    alias = raw.get("alias")
    return FederationHostConfig(
        alias=alias.strip() if isinstance(alias, str) and alias.strip() else None,
        plan=validated,
        bearer_token=bearer_token,
    )


def _connection_plan(raw: Mapping[str, Any]) -> dict[str, Any]:
    if isinstance(raw.get("plan"), Mapping):
        plan = dict(raw["plan"])
    else:
        plan = {
            "schema_version": FEDERATION_IPC_SCHEMA_VERSION,
            "provider_ref": raw.get("provider_ref", "fleet"),
            "endpoint": raw.get("endpoint", ""),
            "credential_ref": raw.get("credential_ref", ""),
            "pinned_installation_id": raw.get("pinned_installation_id", ""),
            "connection_kind": raw.get("connection_kind", "gateway"),
            "tls": raw.get("tls")
            or {
                "schema_version": FEDERATION_IPC_SCHEMA_VERSION,
                "mode": "system_roots",
                "ca_ref": None,
                "server_name_ref": None,
            },
        }
    return plan


def _resolve_credential(credential_ref: str, index: int) -> str:
    prefix, _, name = credential_ref.partition(":")
    if prefix != "env" or not name:
        raise FederationConfigError(
            f"dispatch.remote_hosts[{index}] credential_ref must use env:NAME"
        )
    token = os.environ.get(name)
    if not token:
        raise FederationConfigError(
            f"dispatch.remote_hosts[{index}] credential {credential_ref!r} is missing"
        )
    return token


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _command_value(value: Any) -> tuple[str, ...]:
    if isinstance(value, str):
        return tuple(shlex.split(value)) if value.strip() else ()
    if isinstance(value, Sequence) and not isinstance(value, (bytes, bytearray, str)):
        return tuple(str(part) for part in value if str(part).strip())
    return ()


def _optional_path(value: Any) -> Path | None:
    if isinstance(value, Path):
        return value.expanduser()
    if isinstance(value, str) and value.strip():
        return Path(value).expanduser()
    return None


def _positive_float(value: Any, default: float) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return default
    return result if result > 0 else default


def _positive_int(value: Any, default: int) -> int:
    try:
        result = int(value)
    except (TypeError, ValueError):
        return default
    return result if result > 0 else default


def _timeout(value: float | None, default: float) -> float:
    return _positive_float(value, default)


def _host_identity() -> str:
    raw = os.environ.get("HOSTNAME", "sase-host")
    sanitized = "".join(
        char if (char.isascii() and (char.isalnum() or char in ".-_")) else "-"
        for char in raw.strip()
    ).strip("-")
    return sanitized or "sase-host"


def _disabled_read(operation: str) -> dict[str, Any]:
    return {
        "schema_version": FEDERATION_IPC_SCHEMA_VERSION,
        "operation": operation,
        "disabled": True,
        "hosts": [],
    }


__all__ = [
    "FEDERATION_IPC_SCHEMA_VERSION",
    "FEDERATION_MAX_FRAME_BYTES",
    "FederationConfig",
    "FederationConfigError",
    "FederationFacade",
    "FederationHostConfig",
    "FederationIpcClient",
    "FederationWorkerResponseError",
    "FederationWorkerSettings",
    "FederationWorkerSupervisor",
    "FederationWorkerUnavailable",
    "build_federation_facade",
    "load_federation_config",
    "resolve_federation_worker_command",
]
