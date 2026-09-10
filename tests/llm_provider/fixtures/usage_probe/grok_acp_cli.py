#!/usr/bin/env python3
"""Fake Grok Build CLI for ACP billing usage-probe tests.

Strict mode mirrors the observed Grok Build 1.0.13 ACP billing extension shape.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time


def _record_json(path: str | None, payload: object) -> None:
    if not path:
        return
    with open(path, "a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload) + "\n")


def _write_text_atomic(path: str, text: str) -> None:
    tmp_path = f"{path}.tmp.{os.getpid()}"
    with open(tmp_path, "w", encoding="utf-8") as handle:
        handle.write(text)
    os.replace(tmp_path, path)


def _respond(payload: object) -> None:
    print(json.dumps(payload), flush=True)


def main() -> int:
    argv_path = os.environ.get("SASE_FAKE_GROK_ARGV")
    _record_json(argv_path, sys.argv[1:])

    if sys.argv[1:] == ["--version"]:
        print(
            os.environ.get(
                "SASE_FAKE_GROK_VERSION", "grok 1.0.13 (72a61251fc) [stable]"
            ),
            flush=True,
        )
        return int(os.environ.get("SASE_FAKE_GROK_VERSION_EXIT", "0"))

    if sys.argv[1:] != ["--no-auto-update", "agent", "stdio"]:
        print(f"unexpected argv: {sys.argv[1:]}", file=sys.stderr)
        return 2

    mode = os.environ.get("SASE_FAKE_GROK_MODE", "native")
    pidfile = os.environ.get("SASE_FAKE_GROK_CHILD_PID")
    if mode == "descendants":
        fork = getattr(os, "fork", None)
        if fork is not None:
            child_pid = fork()
            if child_pid == 0:
                time.sleep(60)  # sase-test-wait: descendant survives until reaped
                os._exit(0)
        else:
            child = subprocess.Popen(
                [sys.executable, "-c", "import time; time.sleep(60)"]
            )
            child_pid = child.pid
        if pidfile:
            _write_text_atomic(pidfile, str(child_pid))
        time.sleep(60)  # sase-test-wait: hang until the probe deadline kills us
        return 0

    messages_path = os.environ.get("SASE_FAKE_GROK_MESSAGES")
    for line in sys.stdin:
        message = json.loads(line)
        _record_json(messages_path, message)
        request_id = message.get("id")
        method = message.get("method")
        if method == "initialize":
            _respond(
                {"jsonrpc": "2.0", "id": request_id, "result": {"protocolVersion": 1}}
            )
        elif method == "_x.ai/billing":
            if mode == "method_missing":
                _respond(
                    {
                        "jsonrpc": "2.0",
                        "id": request_id,
                        "error": {"code": -32601, "message": "method_not_found"},
                    }
                )
            elif mode == "auth_required":
                _respond(
                    {
                        "jsonrpc": "2.0",
                        "id": request_id,
                        "error": {
                            "code": -32001,
                            "message": "auth_required: run grok login",
                        },
                    }
                )
            else:
                payload = json.loads(os.environ["SASE_FAKE_GROK_BILLING"])
                _respond({"jsonrpc": "2.0", "id": request_id, "result": payload})
        else:
            _respond(
                {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "error": {
                        "code": -32601,
                        "message": f"unknown method {method}",
                    },
                }
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
