#!/usr/bin/env python3
"""Scripted ``codex app-server`` JSON-RPC transcript fixture for usage tests.

Ignores its own argv (a real ``codex`` binary would see ``app-server`` as
``argv[1]``) and instead branches on ``SASE_CODEX_APP_SERVER_MODE``, mirroring
the generic ``jsonline_cli.py`` fixture's env-driven-mode convention.

Strict modes mirror the observed codex-cli 0.153.4 app-server contract:
``multi_bucket`` accepts unit params for ``account/rateLimits/read``, while
``legacy_params_required`` mirrors the older non-empty params shape.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time

MODE = os.environ.get("SASE_CODEX_APP_SERVER_MODE", "multi_bucket")
PIDFILE = os.environ.get("SASE_CODEX_APP_SERVER_PIDFILE")
REQUEST_LOG = os.environ.get("SASE_CODEX_APP_SERVER_REQUEST_LOG")
SECRET_CANARY = "token=SECRET_CANARY_CODEX"
_UNIT_PARAMS_ERROR = "Invalid request: invalid type: map, expected unit"

_MULTI_BUCKET_RESULT = {
    "rateLimits": {
        "limitId": "codex",
        "limitName": None,
        "primary": {
            "usedPercent": 61.0,
            "windowDurationMins": 300,
            "resetsAt": 1789392969,
        },
        "secondary": {
            "usedPercent": 12.0,
            "windowDurationMins": 10080,
            "resetsAt": 1789408654,
        },
        "planType": "pro",
        "rateLimitReachedType": None,
    },
    "rateLimitsByLimitId": {
        "codex": {
            "limitId": "codex",
            "limitName": None,
            "primary": {
                "usedPercent": 61.0,
                "windowDurationMins": 300,
                "resetsAt": 1789392969,
            },
            "secondary": {
                "usedPercent": 12.0,
                "windowDurationMins": 10080,
                "resetsAt": 1789408654,
            },
            "planType": "pro",
            "rateLimitReachedType": None,
        },
        "codex_bengalfox": {
            "limitName": "GPT-5.3-Codex-Spark",
            "primary": {
                "usedPercent": 0.0,
                "windowDurationMins": 300,
                "resetsAt": 1788821854,
            },
            "secondary": {
                "usedPercent": 0.0,
                "windowDurationMins": 10080,
                "resetsAt": 1789408654,
            },
            "planType": "pro",
            "rateLimitReachedType": None,
        },
    },
}

_LEGACY_RESULT = {
    "rateLimits": {
        "limitId": "codex",
        "limitName": None,
        "primary": {
            "usedPercent": 9.0,
            "windowDurationMins": 10080,
            "resetsAt": 1789392969,
        },
        "secondary": None,
        "planType": "pro",
        "rateLimitReachedType": None,
    },
}

_REACHED_RESULT = {
    "rateLimits": {
        "limitId": "codex",
        "limitName": None,
        "primary": {
            "usedPercent": 100.0,
            "windowDurationMins": 300,
            "resetsAt": 1789392969,
        },
        "secondary": None,
        "planType": "pro",
        "rateLimitReachedType": "primary",
    },
}

_NULL_FIELDS_RESULT = {
    "rateLimits": {
        "limitId": "codex",
        "limitName": None,
        "primary": None,
        "secondary": None,
        "planType": None,
        "rateLimitReachedType": None,
    },
}


def _read_request() -> dict[str, object]:
    line = sys.stdin.readline()
    if not line:
        raise SystemExit(1)
    payload = json.loads(line)
    if not isinstance(payload, dict):
        raise SystemExit(1)
    _record_request(payload)
    return payload


def _record_request(payload: dict[str, object]) -> None:
    if not REQUEST_LOG:
        return
    with open(REQUEST_LOG, "a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, sort_keys=True))
        handle.write("\n")


def _write(payload: dict[str, object]) -> None:
    sys.stdout.write(json.dumps(payload))
    sys.stdout.write("\n")
    sys.stdout.flush()


def _respond_ok(request: dict[str, object], result: object) -> None:
    _write({"jsonrpc": "2.0", "id": request.get("id"), "result": result})


def _respond_error(request: dict[str, object], code: int, message: str) -> None:
    _write(
        {
            "jsonrpc": "2.0",
            "id": request.get("id"),
            "error": {"code": code, "message": message},
        }
    )


def _has_non_empty_params(request: dict[str, object]) -> bool:
    return "params" in request and request.get("params") not in (None, {})


def _handshake() -> None:
    request = _read_request()  # initialize
    _respond_ok(request, {"protocolVersion": 1})
    _read_request()  # initialized (notification, no reply expected)


def main() -> int:
    if MODE == "hang_before_initialize":
        time.sleep(3600)  # sase-test-wait: hang until the transport deadline kills us
        return 0

    _handshake()

    if MODE == "hang_after_handshake":
        time.sleep(3600)  # sase-test-wait: hang until the transport deadline kills us
        return 0

    account_read = _read_request()  # account/read
    if MODE == "api_mode":
        _respond_ok(account_read, {"authMode": "apikey"})
        return 0
    if MODE == "account_read_unauthenticated":
        _respond_error(account_read, 1, "not authenticated")
    elif MODE == "account_read_method_missing":
        _respond_error(account_read, -32601, "method not found: account/read")
    else:
        _respond_ok(account_read, {"authMode": "chatgpt"})

    rate_limits = _read_request()  # account/rateLimits/read
    if MODE == "legacy_params_required":
        if not _has_non_empty_params(rate_limits):
            _respond_error(rate_limits, -32600, _UNIT_PARAMS_ERROR)
            rate_limits = _read_request()  # account/rateLimits/read retry
        if rate_limits.get("params") == {"excludeResetCreditDetails": True}:
            _respond_ok(rate_limits, _MULTI_BUCKET_RESULT)
        else:
            _respond_error(rate_limits, -32602, "legacy params required")
        return 0
    if _has_non_empty_params(rate_limits):
        _respond_error(rate_limits, -32600, _UNIT_PARAMS_ERROR)
        return 0

    if MODE == "unauthenticated":
        _respond_error(rate_limits, 1, "Not logged in. Please sign in.")
        return 0
    if MODE == "method_not_found":
        _respond_error(rate_limits, -32601, "method not found: account/rateLimits/read")
        retry = _read_request()
        _respond_error(retry, -32601, "method not found: account/rateLimits/read")
        return 0
    if MODE == "malformed":
        _respond_ok(rate_limits, {"unexpected": True})
        return 0
    if MODE == "rate_limits_rpc_error":
        _respond_error(
            rate_limits,
            -32042,
            "Vendor drift details\nsecond line should stay out of diagnostics",
        )
        return 0
    if MODE == "null_fields":
        _respond_ok(rate_limits, _NULL_FIELDS_RESULT)
        return 0
    if MODE == "legacy":
        _respond_ok(rate_limits, _LEGACY_RESULT)
        return 0
    if MODE == "reached":
        _respond_ok(rate_limits, _REACHED_RESULT)
        return 0
    if MODE == "notify_then_reply":
        _write(
            {
                "jsonrpc": "2.0",
                "method": "account/rateLimits/updated",
                "params": {},
            }
        )
        _respond_ok(rate_limits, _MULTI_BUCKET_RESULT)
        return 0
    if MODE == "secret_stderr":
        sys.stderr.write(SECRET_CANARY + "\n")
        sys.stderr.flush()
        _respond_ok(rate_limits, _MULTI_BUCKET_RESULT)
        return 0
    if MODE == "hang_on_rate_limits":
        time.sleep(3600)  # sase-test-wait: hang until the transport deadline kills us
        return 0
    if MODE == "descendants":
        child = subprocess.Popen(["sleep", "30"])
        if PIDFILE:
            with open(PIDFILE, "w", encoding="utf-8") as handle:
                handle.write(str(child.pid))
        time.sleep(3600)  # sase-test-wait: keep the child alive until group kill
        return 0

    # "multi_bucket" (default)
    _respond_ok(rate_limits, _MULTI_BUCKET_RESULT)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
