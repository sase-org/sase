"""JSON-line fixture CLI for usage transport tests."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time

MODE = os.environ.get("SASE_USAGE_JSONLINE_MODE", "ok")
PIDFILE = os.environ.get("SASE_USAGE_JSONLINE_PIDFILE")
SECRET_CANARY = "token=SECRET_CANARY_USAGE"


def _read_request() -> dict[str, object]:
    line = sys.stdin.readline()
    if not line:
        raise SystemExit(1)
    payload = json.loads(line)
    if not isinstance(payload, dict):
        raise SystemExit(1)
    return payload


def _write(payload: dict[str, object]) -> None:
    sys.stdout.write(json.dumps(payload))
    sys.stdout.write("\n")
    sys.stdout.flush()


def main() -> int:
    if MODE == "hang":
        time.sleep(3600)  # sase-test-wait: hang until the transport deadline kills us
        return 0
    if MODE == "flood":
        sys.stdout.write("x" * 100_000)
        sys.stdout.flush()
        time.sleep(3600)  # sase-test-wait: keep flooding until the bound kills us
        return 0
    if MODE == "secret_stderr":
        sys.stderr.write(SECRET_CANARY + "\n")
        sys.stderr.flush()
        request = _read_request()
        _write({"jsonrpc": "2.0", "id": request.get("id"), "result": {"ok": True}})
        return 0
    if MODE == "notify_then_reply":
        request = _read_request()
        _write({"jsonrpc": "2.0", "method": "account/rateLimits/updated", "params": {}})
        _write({"jsonrpc": "2.0", "id": "other", "result": {"ignored": True}})
        _write({"jsonrpc": "2.0", "id": request.get("id"), "result": {"ok": True}})
        return 0
    if MODE == "unsolicited_request":
        _write(
            {
                "jsonrpc": "2.0",
                "id": "login-1",
                "method": "login",
                "params": {"token": SECRET_CANARY},
            }
        )
        time.sleep(3600)  # sase-test-wait: wait for the session to refuse login
        return 0
    if MODE == "descendants":
        child = subprocess.Popen(["sleep", "30"])
        if PIDFILE:
            with open(PIDFILE, "w", encoding="utf-8") as handle:
                handle.write(str(child.pid))
        time.sleep(3600)  # sase-test-wait: keep the child alive until group kill
        return 0
    request = _read_request()
    _write({"jsonrpc": "2.0", "id": request.get("id"), "result": {"ok": True}})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
