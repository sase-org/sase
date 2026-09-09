"""A real, loopback-only ``sase_gateway`` process plus a TLS-terminating proxy.

``FleetGatewayClient`` and the federation worker's connection-plan validator both
require an ``https://`` endpoint, but the ``sase_gateway`` binary only ever speaks
plain HTTP (TLS termination is a Tailscale Serve responsibility in production).
This fixture makes an isolated, self-signed loopback endpoint that production
code will actually trust: it generates a throwaway CA and terminates TLS with a
small byte-shuttling proxy in front of the real gateway's plain HTTP port.
``RealGateway.trusted_gateway_client()`` builds a ``FleetGatewayClient`` whose
opener is explicitly configured to trust that CA.
"""

from __future__ import annotations

import contextlib
import selectors
import shutil
import socket
import ssl
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from collections.abc import Generator
from dataclasses import dataclass
from pathlib import Path

import pytest

from sase.dispatch.fleet_client import FleetGatewayClient

_READY_TIMEOUT_SECONDS = 10.0
_SHUTDOWN_TIMEOUT_SECONDS = 5.0


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


def generate_self_signed_loopback_cert(directory: Path) -> tuple[Path, Path]:
    """Write a throwaway self-signed cert/key for ``127.0.0.1`` and return their paths.

    Shells out to the system ``openssl`` CLI rather than importing the
    ``cryptography`` package: ``cryptography`` is only a transitive dependency
    here (pulled in by something else in ``uv.lock``), not a declared project
    dependency, so importing it directly from a test would be fragile.
    """

    openssl = shutil.which("openssl")
    if not openssl:
        pytest.skip("openssl is not installed in this environment")
    cert_path = directory / "loopback-cert.pem"
    key_path = directory / "loopback-key.pem"
    subprocess.run(
        [
            openssl,
            "req",
            "-x509",
            "-newkey",
            "rsa:2048",
            "-keyout",
            str(key_path),
            "-out",
            str(cert_path),
            "-days",
            "1",
            "-nodes",
            "-subj",
            "/CN=127.0.0.1",
            "-addext",
            "subjectAltName=IP:127.0.0.1",
        ],
        check=True,
        capture_output=True,
    )
    return cert_path, key_path


class _TlsTerminatingProxy:
    """Terminates TLS on ``tls_port`` and shuttles bytes to a plain backend port."""

    def __init__(self, *, cert_path: Path, key_path: Path, backend_port: int) -> None:
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.load_cert_chain(str(cert_path), str(key_path))
        self._context = context
        self._backend_port = backend_port
        self._listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._listener.bind(("127.0.0.1", 0))
        self._listener.listen(8)
        self.port = self._listener.getsockname()[1]
        self._closed = False
        self._accept_thread = threading.Thread(target=self._accept_loop, daemon=True)
        self._accept_thread.start()

    def _accept_loop(self) -> None:
        while True:
            try:
                conn, _addr = self._listener.accept()
            except OSError:
                return
            threading.Thread(target=self._serve_one, args=(conn,), daemon=True).start()

    def _serve_one(self, conn: socket.socket) -> None:
        try:
            tls_conn = self._context.wrap_socket(conn, server_side=True)
        except (ssl.SSLError, OSError):
            conn.close()
            return
        with contextlib.closing(tls_conn):
            with socket.create_connection(
                ("127.0.0.1", self._backend_port), timeout=5.0
            ) as backend:
                self._pump(tls_conn, backend)

    @staticmethod
    def _pump(tls_conn: ssl.SSLSocket, backend: socket.socket) -> None:
        selector = selectors.DefaultSelector()
        selector.register(tls_conn, selectors.EVENT_READ)
        selector.register(backend, selectors.EVENT_READ)
        try:
            while True:
                for key, _events in selector.select(timeout=30.0):
                    src, dst = (
                        (tls_conn, backend)
                        if key.fileobj is tls_conn
                        else (backend, tls_conn)
                    )
                    try:
                        data = src.recv(65536)
                    except OSError:
                        return
                    if not data:
                        return
                    try:
                        dst.sendall(data)
                    except OSError:
                        return
        finally:
            selector.close()

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        with contextlib.suppress(OSError):
            self._listener.close()
        self._accept_thread.join(timeout=_SHUTDOWN_TIMEOUT_SECONDS)


@dataclass(frozen=True)
class RealGateway:
    """A running real ``sase_gateway`` process reachable over a trusted HTTPS proxy."""

    home: Path
    https_endpoint: str
    plain_health_url: str
    cert_path: Path

    def trusted_gateway_client(
        self, *, timeout_seconds: float = 5.0
    ) -> FleetGatewayClient:
        """A ``FleetGatewayClient`` whose opener trusts this fixture's self-signed CA.

        ``urllib.request.urlopen``'s module-level default opener is built once
        and cached for the life of the process, so setting ``SSL_CERT_FILE``
        after that first call has no effect. Build and inject an explicit
        opener instead of relying on process-wide HTTPS defaults.
        """

        context = ssl.create_default_context(cafile=str(self.cert_path))
        director = urllib.request.build_opener(
            urllib.request.HTTPSHandler(context=context)
        )
        return FleetGatewayClient(
            timeout_seconds=timeout_seconds, opener=_UrlopenAdapter(director)
        )


class _UrlopenAdapter:
    """Gives an ``OpenerDirector`` the ``urlopen(request, *, timeout)`` shape
    ``FleetGatewayClient`` expects (matching the plain ``urllib.request`` module API,
    which is its default ``opener``)."""

    def __init__(self, director: urllib.request.OpenerDirector) -> None:
        self._director = director

    def urlopen(self, request: urllib.request.Request, *, timeout: float) -> object:
        return self._director.open(request, timeout=timeout)


def _gateway_command() -> tuple[str, ...]:
    candidate = Path(sys.executable).parent / "sase_gateway"
    if candidate.is_file():
        return (str(candidate),)
    packaged = shutil.which("sase_gateway")
    if packaged:
        return (packaged,)
    pytest.skip("sase_gateway binary is not installed in this environment")


def _wait_until_healthy(url: str, *, proc: subprocess.Popen[bytes]) -> None:
    deadline = time.monotonic() + _READY_TIMEOUT_SECONDS
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            raise RuntimeError(
                f"sase_gateway exited before becoming healthy (rc={proc.returncode})"
            )
        try:
            with urllib.request.urlopen(url, timeout=0.5) as response:
                if response.status == 200:
                    return
        except (urllib.error.URLError, OSError) as exc:
            last_error = exc
        time.sleep(0.05)  # sase-test-wait: polling real subprocess startup
    raise RuntimeError(f"sase_gateway did not become healthy in time: {last_error}")


@contextlib.contextmanager
def real_gateway(tmp_path: Path) -> Generator[RealGateway]:
    """Spawn a real, isolated ``sase_gateway`` reachable over a trusted loopback HTTPS proxy."""

    home = tmp_path / "gateway_home"
    home.mkdir(parents=True, exist_ok=True)
    cert_path, key_path = generate_self_signed_loopback_cert(tmp_path)
    plain_port = _free_port()
    argv = [
        *_gateway_command(),
        "--bind",
        f"127.0.0.1:{plain_port}",
        "--sase-home",
        str(home),
    ]
    proc = subprocess.Popen(
        argv,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    plain_health_url = f"http://127.0.0.1:{plain_port}/api/v1/health"
    try:
        _wait_until_healthy(plain_health_url, proc=proc)
        proxy = _TlsTerminatingProxy(
            cert_path=cert_path, key_path=key_path, backend_port=plain_port
        )
        try:
            yield RealGateway(
                home=home,
                https_endpoint=f"https://127.0.0.1:{proxy.port}",
                plain_health_url=plain_health_url,
                cert_path=cert_path,
            )
        finally:
            proxy.close()
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=_SHUTDOWN_TIMEOUT_SECONDS)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=_SHUTDOWN_TIMEOUT_SECONDS)
