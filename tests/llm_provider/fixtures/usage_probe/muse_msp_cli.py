#!/usr/bin/env python3
"""Fake Muse Code CLI for ``muse serve`` (MSP) usage-probe tests.

The default mode mirrors what Muse Code 1.3.0 was observed to do: a cold host
answers ``usage/read`` with ``{}``, and a ``turn/start`` on an echo-provider
session makes the host learn its subscription usage a little later. Every
frame the probe sends is recorded so tests can assert on what was *not* sent.
"""

from __future__ import annotations

import json
import os
import sys
import time
import uuid

_FINGERPRINT = "sha256:7469c9e352e67def4a59df7e439984d7194fa351e1c8b7abb34060fd977ced81"
_LIVE_USAGE = {
    "observedAtMs": 1789921255705,
    "tier": "27681631238169137",
    "weekly": {"resetsAtMs": 1789948800000, "usedPercent": 0},
    "window": {
        "resetsAtMs": 1789935797000,
        "usedPercent": 0,
        "windowDurationMins": 300,
    },
}


def _record_json(path: str | None, payload: object) -> None:
    if not path:
        return
    with open(path, "a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload) + "\n")


def _emit(payload: object) -> None:
    print(json.dumps(payload), flush=True)


def _result(request_id: object, result: object) -> None:
    _emit({"jsonrpc": "2.0", "id": request_id, "result": result})


def _error(request_id: object, code: int, message: str, kind: str) -> None:
    _emit(
        {
            "jsonrpc": "2.0",
            "id": request_id,
            "error": {"code": code, "message": message, "data": {"kind": kind}},
        }
    )


def _is_uuid7(value: object) -> bool:
    try:
        return uuid.UUID(str(value)).version == 7
    except ValueError:
        return False


def _usage_payload() -> object:
    override = os.environ.get("SASE_FAKE_MUSE_USAGE")
    if override is not None:
        return json.loads(override)
    return dict(_LIVE_USAGE)


def main() -> int:
    argv_path = os.environ.get("SASE_FAKE_MUSE_ARGV")
    _record_json(
        argv_path,
        {
            "argv": sys.argv[1:],
            "no_auto_update": os.environ.get("MUSE_NO_AUTO_UPDATE"),
            "cwd": os.getcwd(),
        },
    )
    if sys.argv[1:] != ["serve", "--no-session-log", "--disable-shell"]:
        print(f"unexpected argv: {sys.argv[1:]}", file=sys.stderr)
        return 2

    mode = os.environ.get("SASE_FAKE_MUSE_MODE", "native")
    messages_path = os.environ.get("SASE_FAKE_MUSE_MESSAGES")
    mint_after_polls = int(os.environ.get("SASE_FAKE_MUSE_MINT_AFTER_POLLS", "2"))
    if mode == "hang":
        time.sleep(60)  # sase-test-wait: hang until the probe deadline kills us
        return 0

    initialized = False
    turn_started = False
    polls_since_turn = 0
    for line in sys.stdin:
        message = json.loads(line)
        _record_json(messages_path, message)
        request_id = message.get("id")
        method = message.get("method")
        params = message.get("params") or {}
        if method == "initialized":
            initialized = "id" not in message
            continue
        if method == "initialize":
            _result(
                request_id,
                {
                    "schema": {
                        "fingerprint": os.environ.get(
                            "SASE_FAKE_MUSE_FINGERPRINT", _FINGERPRINT
                        ),
                        "version": 1,
                    },
                    "serverInfo": {"name": "muse", "version": "1.3.0"},
                },
            )
        elif not initialized:
            _error(request_id, -32600, "not initialized", "notInitialized")
        elif method == "session/start":
            if not _is_uuid7(params.get("commandId")):
                _error(
                    request_id,
                    -32602,
                    "invalid session/start commandId: expected UUIDv7",
                    "invalidParams",
                )
                continue
            session = {
                "sessionId": "01a0bfd8-88b9-7661-a94b-07b71bcc5c77",
                "providerId": params.get("providerId"),
                "modelId": None,
                "status": "idle",
            }
            if mode == "guard_provider":
                session["providerId"] = "meta"
            elif mode == "guard_model":
                session["modelId"] = "muse-spark-1.3"
            elif mode == "session_payload_missing":
                _result(request_id, {"viewCursor": "x"})
                continue
            _emit({"jsonrpc": "2.0", "method": "session/started", "params": session})
            _result(request_id, {"session": session, "viewCursor": "x"})
        elif method == "turn/start":
            if mode == "turn_rejected":
                _error(request_id, -32602, "invalid params", "invalidParams")
                continue
            if not _is_uuid7(params.get("commandId")):
                _error(request_id, -32602, "expected UUIDv7", "invalidParams")
                continue
            turn_started = True
            ack = {
                "commandId": params["commandId"],
                "disposition": "queued" if mode == "turn_ack_queued" else "started",
                "startedNewTurn": mode != "turn_ack_queued",
                "status": "accepted",
                "turnId": params["commandId"],
            }
            _result(request_id, ack)
            if mode == "unsolicited_request":
                _emit(
                    {
                        "jsonrpc": "2.0",
                        "id": "srv-1",
                        "method": "approval/request",
                        "params": {},
                    }
                )
        elif method == "usage/read":
            if mode == "usage_method_missing":
                _error(request_id, -32601, "method not found", "methodNotFound")
                continue
            if mode == "usage_read_error":
                _error(request_id, -32000, "internal host failure", "internal")
                continue
            if turn_started:
                polls_since_turn += 1
            minted = (
                turn_started
                and mode != "never_mint"
                and polls_since_turn > mint_after_polls
            )
            if not minted:
                _result(request_id, {})
                continue
            usage = _usage_payload()
            _emit({"jsonrpc": "2.0", "method": "usage/changed", "params": usage})
            _result(request_id, {"usage": usage})
        else:
            _error(request_id, -32601, f"unknown method {method}", "methodNotFound")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
