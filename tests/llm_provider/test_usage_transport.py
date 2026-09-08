"""Bounded JSON-line transport: hang, flood, secrets, notifications, cleanup."""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

import pytest

from sase.testing.usage_synthetic import SECRET_CANARY
from sase.llm_provider.usage.transport import JsonLineSession, JsonLineTransportError

_FIXTURE = (
    Path(__file__).resolve().parent / "fixtures" / "usage_probe" / "jsonline_cli.py"
)


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def _session(mode: str, **env: str) -> JsonLineSession:
    return JsonLineSession(
        (sys.executable, str(_FIXTURE)),
        deadline_at=time.time() + 2.0,
        env={**os.environ, "SASE_USAGE_JSONLINE_MODE": mode, **env},
        max_line_bytes=2048,
        max_total_bytes=8192,
        max_stderr_bytes=2048,
    )


def test_jsonline_correlates_response_and_skips_notifications() -> None:
    with _session("notify_then_reply") as session:
        session.send(
            {"jsonrpc": "2.0", "id": 7, "method": "account/read", "params": {}}
        )
        payload = session.read_response(7)
    assert payload["result"] == {"ok": True}


def test_jsonline_hang_times_out() -> None:
    with pytest.raises(JsonLineTransportError) as caught:
        with _session("hang") as session:
            session.send({"jsonrpc": "2.0", "id": 1, "method": "ping"})
            session.read_response(1)
    assert caught.value.code == "timeout"


def test_jsonline_oversized_output_is_bounded() -> None:
    with pytest.raises(JsonLineTransportError) as caught:
        with _session("flood") as session:
            session.send({"jsonrpc": "2.0", "id": 1, "method": "ping"})
            session.read_response(1)
    assert caught.value.code in {"stdout_overflow", "timeout"}


def test_jsonline_secret_stderr_is_not_returned_as_payload() -> None:
    with _session("secret_stderr") as session:
        session.send({"jsonrpc": "2.0", "id": 3, "method": "ping"})
        payload = session.read_response(3)
    assert payload["result"] == {"ok": True}
    assert SECRET_CANARY not in str(payload)


def test_jsonline_refuses_unsolicited_login_request() -> None:
    with pytest.raises(JsonLineTransportError) as caught:
        with _session("unsolicited_request") as session:
            session.read_response("never")
    assert caught.value.code == "unsolicited_request"
    assert SECRET_CANARY not in str(caught.value)


def test_jsonline_descendant_cleanup(tmp_path: Path) -> None:
    pidfile = tmp_path / "child.pid"
    with pytest.raises(JsonLineTransportError):
        with _session(
            "descendants", SASE_USAGE_JSONLINE_PIDFILE=str(pidfile)
        ) as session:
            session.read_response(1)
    child_pid = int(pidfile.read_text(encoding="utf-8"))
    assert not _pid_alive(child_pid)
