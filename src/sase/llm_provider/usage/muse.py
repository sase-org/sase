"""Muse Code subscription usage collector (a free MSP echo-mint probe)."""

from __future__ import annotations

import logging
import os
import time
import uuid
from collections.abc import Mapping
from typing import Any

from sase.core.rust import require_rust_binding
from sase.llm_provider.usage._strategy import (
    ProbeStrategy,
    classify_probe_failure,
    run_probe_strategies,
)
from sase.llm_provider.usage.transport import JsonLineSession, JsonLineTransportError
from sase.llm_provider.usage.types import (
    UsageCollectionOutcome,
    UsageProbeContext,
    UsageReasonCode,
    bounded_probe_diagnostic,
    validated_status_observation,
)

_MUSE_CLI_NAME = "muse"
# The provider sets this for `muse exec` too: without it the ``~/.local/bin/muse``
# launcher swaps the real binary hourly, possibly under a live probe.
_MUSE_NO_AUTO_UPDATE_ENV = "MUSE_NO_AUTO_UPDATE"
_SERVE_ARGS = ("serve", "--no-session-log", "--disable-shell")
# MSP requires ``clientInfo.name`` to match ``^[a-z0-9_]+$``.
_CLIENT_NAME = "sase"
_CLIENT_VERSION = "0"
# ``InitializeResult.schema.fingerprint`` of the Muse Code 1.3.0 host this probe
# was written against. Muse's launcher self-updates and the fingerprint churns
# with every release, so a mismatch only warns; it must never gate the probe.
_MSP_SCHEMA_FINGERPRINT = (
    "sha256:7469c9e352e67def4a59df7e439984d7194fa351e1c8b7abb34060fd977ced81"
)
# OBSERVED, NOT CONTRACTED: a cold ``muse serve`` host reports ``usage/read`` as
# ``{}`` forever, but a ``turn/start`` on a session started with
# ``providerId: "echo"`` makes it mint credentials and learn its subscription
# usage ~2.5 s later, with no model call and no tokens. If a future Muse defers
# the mint to real provider dispatch the probe degrades to absence (safe); the
# echo-session guard below is what keeps the unsafe failure impossible.
_ECHO_PROVIDER_ID = "echo"
_POLL_INTERVAL_SECONDS = 0.25
# The mint lands 2.4-2.9 s after ``turn/start``; this leaves ~3x headroom while
# staying well inside USAGE_REFRESH_PROVIDER_DEADLINE_SECONDS.
_MINT_WAIT_SECONDS = 8.0
# Stop polling this long before the session deadline so a slow host reads as
# absence instead of a transport timeout.
_POLL_TAIL_MARGIN_SECONDS = 0.1
_SUBPROCESS_CLEANUP_MARGIN_SECONDS = 0.25
_MIN_SUBPROCESS_DEADLINE_SECONDS = 0.1

log = logging.getLogger(__name__)


def collect_muse_usage(
    context: UsageProbeContext, executable: str | None = None
) -> dict[str, Any]:
    """Collect Muse Code's subscription usage windows without a model call."""
    command = executable or context.executable or _MUSE_CLI_NAME
    deadline_at = _subprocess_deadline(context)
    env = {**os.environ, _MUSE_NO_AUTO_UPDATE_ENV: "1"}
    try:
        with JsonLineSession(
            (command, *_SERVE_ARGS),
            deadline_at=deadline_at,
            cwd=context.working_directory,
            env=env,
        ) as session:
            return run_probe_strategies(
                context,
                (
                    ProbeStrategy(
                        "echo_mint",
                        lambda attempt_context: _collect_echo_mint(
                            session, attempt_context, deadline_at
                        ),
                    ),
                ),
                logger=log,
            )
    except FileNotFoundError:
        return _status(
            context,
            outcome="error",
            reason_code="not_installed",
            diagnostic="muse_executable_not_found",
        )
    except OSError:
        return _status(
            context,
            outcome="error",
            reason_code="probe_failed",
            diagnostic="muse_msp_io_error",
        )
    except JsonLineTransportError as exc:
        return _transport_status(exc, context)


def _collect_echo_mint(
    session: JsonLineSession, context: UsageProbeContext, deadline_at: float
) -> dict[str, Any]:
    """Run the minimal MSP sequence and normalize the resulting ``usage/read``.

    Nothing speculative goes on this connection: the one trial that failed to
    mint had interleaved a method the host rejected with ``-32601``.
    """
    initialized = _call(
        session,
        "initialize",
        {"clientInfo": {"name": _CLIENT_NAME, "version": _CLIENT_VERSION}},
    )
    failure = _failure_status(initialized, context, method="initialize")
    if failure is not None:
        return failure
    _warn_on_schema_drift(initialized.get("result"))
    # Without this notification every later call fails
    # ``-32600 {"kind": "notInitialized"}``.
    session.send({"jsonrpc": "2.0", "method": "initialized"})

    started = _call(
        session,
        "session/start",
        {
            "commandId": _uuid7(),
            "workspaceRoot": os.path.abspath(context.working_directory or os.getcwd()),
            "providerId": _ECHO_PROVIDER_ID,
        },
    )
    failure = _failure_status(started, context, method="session/start")
    if failure is not None:
        return failure
    started_session = _result_member(started, "session")
    if started_session is None:
        return _status(
            context,
            outcome="error",
            reason_code="malformed_payload",
            diagnostic="muse_session_start_payload_missing",
        )
    # Echo-session guard. This assumes the host honours ``providerId: "echo"``
    # and leaves the session unbound to a model. If a future Muse ignores or
    # rejects it, the next call would spend a real model turn on every refresh
    # tick, so stop before sending any turn.
    if (
        started_session.get("providerId") != _ECHO_PROVIDER_ID
        or started_session.get("modelId") is not None
    ):
        return _status(
            context,
            outcome="error",
            reason_code="vendor_drift",
            diagnostic="muse_echo_session_guard_failed",
        )
    session_id = started_session.get("sessionId")
    if not isinstance(session_id, str) or not session_id:
        return _status(
            context,
            outcome="error",
            reason_code="malformed_payload",
            diagnostic="muse_session_start_payload_missing",
        )

    turn = _call(
        session,
        "turn/start",
        {
            "commandId": _uuid7(),
            "sessionId": session_id,
            "input": [{"type": "text", "text": "hi"}],
            "reasoningEffort": "none",
        },
    )
    failure = _failure_status(turn, context, method="turn/start")
    if failure is not None:
        return failure
    ack = turn.get("result")
    if (
        not isinstance(ack, Mapping)
        or ack.get("status") != "accepted"
        or ack.get("disposition") != "started"
    ):
        return _status(
            context,
            outcome="error",
            reason_code="vendor_drift",
            diagnostic="muse_turn_ack_unexpected",
        )

    return _poll_usage(session, context, deadline_at)


def _poll_usage(
    session: JsonLineSession, context: UsageProbeContext, deadline_at: float
) -> dict[str, Any]:
    """Poll ``usage/read`` until the mint lands or the wait budget runs out.

    The shared transport discards server notifications, so awaiting
    ``usage/changed`` would need a transport change; ``usage/read`` costs ~1 ms.
    A budget that runs out with no ``usage`` member is truthful absence (a
    logged-out or never-minted host), not an error, and is normalized by core
    into the same authoritative-empty observation as any other absent ``usage``.
    That observation clears the stored Muse windows, so one missed mint blanks
    the header weekly indicator until the next tick; the budget above makes a
    miss rare and it is accepted knowingly.
    """
    poll_until = min(
        time.time() + _MINT_WAIT_SECONDS,
        deadline_at - _POLL_TAIL_MARGIN_SECONDS,
    )
    request_number = 0
    while True:
        request_number += 1
        response = _call(session, "usage/read", {}, request_number=request_number)
        failure = _failure_status(response, context, method="usage/read")
        if failure is not None:
            return failure
        result = response.get("result")
        if not isinstance(result, Mapping):
            return _status(
                context,
                outcome="error",
                reason_code="malformed_payload",
                diagnostic="muse_usage_read_payload_missing",
            )
        remaining = poll_until - time.time()
        if "usage" in result or remaining <= 0:
            return _observation_from_payload(result, context)
        time.sleep(min(_POLL_INTERVAL_SECONDS, remaining))


def _call(
    session: JsonLineSession,
    method: str,
    params: Mapping[str, Any],
    *,
    request_number: int | None = None,
) -> dict[str, Any]:
    suffix = "" if request_number is None else f"-{request_number}"
    request_id = f"sase-muse-{method.replace('/', '-')}{suffix}"
    session.send(
        {"jsonrpc": "2.0", "id": request_id, "method": method, "params": dict(params)}
    )
    return session.read_response(request_id)


def _result_member(
    response: Mapping[str, Any], member: str
) -> Mapping[str, Any] | None:
    result = response.get("result")
    if not isinstance(result, Mapping):
        return None
    value = result.get(member)
    return value if isinstance(value, Mapping) else None


def _observation_from_payload(
    payload: Mapping[str, Any], context: UsageProbeContext
) -> dict[str, Any]:
    binding = require_rust_binding("provider_usage_normalize_muse_usage")
    observation = binding(
        {
            "schema_version": 1,
            "payload": dict(payload),
            "provider": context.provider,
            "context_id": context.context_id,
            "account_generation": context.account_generation,
            "request_started_at": float(context.request_started_at),
            "now": _clock_for_context(context),
        }
    )
    if not isinstance(observation, dict):
        return _status(
            context,
            outcome="error",
            reason_code="malformed_payload",
            diagnostic="muse_usage_read_payload_missing",
        )
    return observation


def _warn_on_schema_drift(initialize_result: object) -> None:
    schema = (
        initialize_result.get("schema")
        if isinstance(initialize_result, Mapping)
        else None
    )
    fingerprint = schema.get("fingerprint") if isinstance(schema, Mapping) else None
    if fingerprint != _MSP_SCHEMA_FINGERPRINT:
        log.warning(
            "muse MSP schema fingerprint %s differs from the probed %s; proceeding",
            bounded_probe_diagnostic(fingerprint),
            _MSP_SCHEMA_FINGERPRINT,
        )


def _failure_status(
    response: Mapping[str, Any], context: UsageProbeContext, *, method: str
) -> dict[str, Any] | None:
    """Map a JSON-RPC error response to a status observation.

    Only request-shape rejection is mapped. No logged-out shape has been
    observed, so no auth wording is guessed at here: a logged-out host reports
    absence through the deadline path instead.
    """
    error = response.get("error")
    if not isinstance(error, Mapping):
        return None
    slug = method.replace("/", "_")
    if classify_probe_failure("probe_failed", json_rpc_error=error) == "vendor_drift":
        return _status(
            context,
            outcome="error",
            reason_code="vendor_drift",
            diagnostic=f"muse_msp_{slug}_rejected",
        )
    return _status(
        context,
        outcome="error",
        reason_code="probe_failed",
        diagnostic=f"muse_msp_{slug}_error",
    )


def _transport_status(
    exc: JsonLineTransportError, context: UsageProbeContext
) -> dict[str, Any]:
    if exc.code == "timeout":
        return _status(
            context,
            outcome="error",
            reason_code="timeout",
            diagnostic="muse_msp_probe_timeout",
        )
    if exc.code == "malformed_response":
        return _status(
            context,
            outcome="error",
            reason_code="parse_error",
            diagnostic="muse_msp_malformed_response",
        )
    return _status(
        context,
        outcome="error",
        reason_code="probe_failed",
        diagnostic=f"muse_msp_{exc.code}",
    )


def _status(
    context: UsageProbeContext,
    outcome: UsageCollectionOutcome,
    reason_code: UsageReasonCode | None = None,
    diagnostic: str | None = None,
) -> dict[str, Any]:
    return validated_status_observation(
        context,
        now=_clock_for_context(context),
        outcome=outcome,
        reason_code=reason_code,
        diagnostic=diagnostic,
    )


def _clock_for_context(context: UsageProbeContext) -> float:
    return max(time.time(), context.request_started_at)


def _subprocess_deadline(context: UsageProbeContext) -> float:
    now = time.time()
    remaining = context.deadline_at - now
    if remaining <= _MIN_SUBPROCESS_DEADLINE_SECONDS:
        return context.deadline_at
    return max(
        now + _MIN_SUBPROCESS_DEADLINE_SECONDS,
        context.deadline_at - _SUBPROCESS_CLEANUP_MARGIN_SECONDS,
    )


def _uuid7() -> str:
    """Return a fresh UUIDv7; the host rejects v4 ``commandId`` values.

    ``uuid.uuid7`` only exists on Python 3.14+, and SASE supports 3.12.
    """
    unix_ms = time.time_ns() // 1_000_000
    rand_a = int.from_bytes(os.urandom(2), "big") & 0x0FFF
    rand_b = int.from_bytes(os.urandom(8), "big") & ((1 << 62) - 1)
    value = (unix_ms << 80) | (0x7 << 76) | (rand_a << 64) | (0b10 << 62) | rand_b
    return str(uuid.UUID(int=value))
