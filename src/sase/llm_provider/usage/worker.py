"""Isolated usage-probe worker. Invoked as ``python -m sase.llm_provider.usage.worker``."""

from __future__ import annotations

import json
import sys
import time
from typing import Any
from collections.abc import Mapping

from sase.llm_provider.usage.probe import load_probe_plugin, probe_in_process
from sase.llm_provider.usage.types import (
    UsageProbeContext,
    validated_status_observation,
)

_MAX_STDIN_BYTES = 1_048_576


def main(argv: list[str] | None = None) -> int:  # noqa: ARG001
    """Read one JSON request from stdin and write one observation to stdout."""
    raw = sys.stdin.buffer.read(_MAX_STDIN_BYTES + 1)
    if len(raw) > _MAX_STDIN_BYTES:
        return _fail_hard()
    try:
        request = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return _fail_hard()
    if not isinstance(request, dict):
        return _fail_hard()
    observation = _handle_worker_request(request)
    sys.stdout.write(json.dumps(observation, separators=(",", ":")))
    sys.stdout.write("\n")
    return 0


def _handle_worker_request(request: Mapping[str, Any]) -> dict[str, Any]:
    """Execute one in-process probe for an isolated worker request."""
    now = time.time()
    try:
        context = UsageProbeContext.from_json(request["context"])
    except (KeyError, TypeError, ValueError):
        return {
            "schema_version": 1,
            "provider": "unknown",
            "context_id": "worker",
            "account_generation": 0,
            "ordering_token": now,
            "received_at": now,
            "source": "probe",
            "outcome": "error",
            "reason_code": "malformed_payload",
            "diagnostic": "usage probe worker request was malformed",
            "completeness": "partial",
            "authoritative_empty": False,
            "account_mode": None,
            "plan": None,
            "windows": [],
        }
    plugin_spec = request.get("plugin")
    if plugin_spec is not None and not isinstance(plugin_spec, dict):
        return validated_status_observation(
            context,
            now=now,
            outcome="error",
            reason_code="malformed_payload",
        )
    try:
        plugin = load_probe_plugin(plugin_spec, context)
    except Exception:
        return validated_status_observation(
            context,
            now=now,
            outcome="error",
            reason_code="probe_failed",
        )
    return probe_in_process(plugin, context, now=now)


def _fail_hard() -> int:
    sys.stdout.write("{}\n")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
