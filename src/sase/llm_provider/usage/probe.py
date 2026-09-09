"""Dispatch optional usage probes, including isolated worker execution."""

from __future__ import annotations

import importlib
import json
import logging
import os
import sys
import tempfile
import time
from collections.abc import Mapping
from typing import Any

from sase.llm_provider._registry_plugins import load_llm_plugin_class
from sase.llm_provider.usage.config import collection_skip_reason
from sase.llm_provider.usage.transport import (
    DEFAULT_MAX_STDERR_BYTES,
    DEFAULT_MAX_TOTAL_BYTES,
    bounded_communicate,
    spawn_killable_process,
)
from sase.llm_provider.usage.types import (
    UsageProbeContext,
    UsageProbeResult,
    bounded_probe_diagnostic,
    observation_schema_version,
    validate_observation,
    validated_status_observation,
)

log = logging.getLogger(__name__)

DEFAULT_PROBE_DEADLINE_SECONDS = 10.0
_WORKER_MODULE = "sase.llm_provider.usage.worker"
_ALLOWED_ENV_NAMES = frozenset(
    {
        "CODEX_HOME",
        "HOME",
        "LANG",
        "LC_ALL",
        "LC_CTYPE",
        "LD_LIBRARY_PATH",
        "LOGNAME",
        "PATH",
        "PWD",
        "PYTHONHOME",
        "PYTHONPATH",
        "PYTHONSAFEPATH",
        "REQUESTS_CA_BUNDLE",
        "SSL_CERT_FILE",
        "TERM",
        "TMPDIR",
        "TZ",
        "USER",
        "VIRTUAL_ENV",
    }
)
_ALLOWED_ENV_PREFIXES = ("LC_", "PYTHON", "SASE_", "XDG_")
_DENIED_ENV_MARKERS = ("KEY", "TOKEN", "SECRET", "PASSWORD", "CREDENTIAL", "AUTH")


def run_usage_probe(
    context: UsageProbeContext,
    *,
    isolate: bool = True,
    plugin: object | None = None,
    plugin_spec: Mapping[str, Any] | None = None,
    now: float | None = None,
    env: Mapping[str, str] | None = None,
) -> UsageProbeResult:
    """Run ``llm_usage_probe`` for *context*.

    Missing hooks become ``unsupported``. Unexpected plugin exceptions become
    sanitized ``error`` observations. Isolation is the production path so a
    hanging plugin can be killed.
    """
    skip = collection_skip_reason(context.provider)
    if skip is not None:
        return UsageProbeResult(skipped=skip)
    clock = time.time() if now is None else now
    if isolate:
        return _run_isolated(context, plugin_spec=plugin_spec, now=clock, env=env)
    loaded = plugin if plugin is not None else load_probe_plugin(plugin_spec, context)
    return UsageProbeResult(observation=probe_in_process(loaded, context, now=clock))


def record_passive_usage_observation(
    observation: Mapping[str, Any],
    *,
    now: float | None = None,
) -> dict[str, Any] | None:
    """Validate a fenced stream observation. Persistence is the store's job.

    Returns ``None`` when collection is disabled by flag or configuration.
    """
    provider = str(observation.get("provider") or "")
    skip = collection_skip_reason(provider or "_")
    if skip is not None:
        return None
    clock = time.time() if now is None else now
    payload = dict(observation)
    payload.setdefault("source", "stream_event")
    return validate_observation(payload, now=clock)


def probe_in_process(
    plugin: object, context: UsageProbeContext, *, now: float
) -> dict[str, Any]:
    """Call ``llm_usage_probe`` on *plugin* without spawning a worker."""
    method = getattr(plugin, "llm_usage_probe", None)
    if method is None:
        return validated_status_observation(context, now=now, outcome="unsupported")
    try:
        raw = method(context=context)
    except TypeError:
        try:
            raw = method(context)
        except Exception:
            log.warning("usage probe failed for provider %r", context.provider)
            return validated_status_observation(
                context,
                now=now,
                outcome="error",
                reason_code="probe_failed",
            )
    except Exception:
        log.warning("usage probe failed for provider %r", context.provider)
        return validated_status_observation(
            context,
            now=now,
            outcome="error",
            reason_code="probe_failed",
        )
    if raw is None:
        return validated_status_observation(context, now=now, outcome="unsupported")
    if not isinstance(raw, dict):
        return validated_status_observation(
            context,
            now=now,
            outcome="error",
            reason_code="malformed_payload",
        )
    try:
        validation_now = max(time.time(), now)
        return validate_observation(
            _bind_observation(raw, context, validation_now),
            now=validation_now,
        )
    except (TypeError, ValueError, AttributeError):
        log.warning(
            "usage probe returned an invalid observation for provider %r",
            context.provider,
        )
        return validated_status_observation(
            context,
            now=now,
            outcome="error",
            reason_code="malformed_payload",
        )


def load_probe_plugin(
    plugin_spec: Mapping[str, Any] | None, context: UsageProbeContext
) -> object:
    """Instantiate a plugin from *plugin_spec* or the provider entry point."""
    spec = dict(plugin_spec or {})
    kind = str(spec.get("kind") or "entry_point")
    if kind == "import":
        module_name = str(spec["module"])
        qualname = str(spec["qualname"])
        module = importlib.import_module(module_name)
        plugin_cls = getattr(module, qualname)
        return plugin_cls()
    name = str(spec.get("name") or context.provider)
    plugin_cls = load_llm_plugin_class(name)
    if plugin_cls is None:
        raise LookupError(f"unknown LLM provider: {name}")
    return plugin_cls()


def default_probe_context(
    provider: str,
    *,
    now: float | None = None,
    deadline_seconds: float = DEFAULT_PROBE_DEADLINE_SECONDS,
    context_id: str = "probe",
    account_generation: int = 1,
    operation_id: str = "op",
    executable: str | None = None,
    auth_context: str = "",
    working_directory: str | None = None,
) -> UsageProbeContext:
    """Build a probe context with request-start ordering."""
    started = time.time() if now is None else now
    return UsageProbeContext(
        schema_version=observation_schema_version(),
        provider=provider,
        deadline_at=started + deadline_seconds,
        context_id=context_id,
        account_generation=account_generation,
        operation_id=operation_id,
        request_started_at=started,
        executable=executable,
        auth_context=auth_context,
        working_directory=working_directory,
    )


def worker_environ(extra: Mapping[str, str] | None = None) -> dict[str, str]:
    """Return a filtered environment with no secret-bearing values."""
    env: dict[str, str] = {}
    for name, value in os.environ.items():
        if _env_allowed(name):
            env[name] = value
    if extra:
        for name, value in extra.items():
            if _env_allowed(name):
                env[name] = value
    return env


def _run_isolated(
    context: UsageProbeContext,
    *,
    plugin_spec: Mapping[str, Any] | None,
    now: float,
    env: Mapping[str, str] | None,
) -> UsageProbeResult:
    spec = dict(plugin_spec or {"kind": "entry_point", "name": context.provider})
    request = {"plugin": spec, "context": context.to_json()}
    payload = json.dumps(request, separators=(",", ":")).encode("utf-8")
    tmp_cwd: tempfile.TemporaryDirectory[str] | None = None
    cwd = context.working_directory
    if not cwd:
        tmp_cwd = tempfile.TemporaryDirectory(prefix="sase-usage-probe-")
        cwd = tmp_cwd.name
    process = spawn_killable_process(
        (sys.executable, "-m", _WORKER_MODULE),
        cwd=cwd,
        env=worker_environ(env),
    )
    try:
        stdout, stderr, overflow = bounded_communicate(
            process,
            payload,
            deadline_at=context.deadline_at,
            max_stdout_bytes=DEFAULT_MAX_TOTAL_BYTES,
            max_stderr_bytes=DEFAULT_MAX_STDERR_BYTES,
        )
    finally:
        if tmp_cwd is not None:
            tmp_cwd.cleanup()
    _log_worker_stderr(context.provider, stderr, stdout=stdout)
    if overflow == "timeout":
        return UsageProbeResult(
            observation=validated_status_observation(
                context,
                now=max(time.time(), now),
                outcome="error",
                reason_code="timeout",
            )
        )
    if overflow in {"stdout_overflow", "stderr_overflow"}:
        return UsageProbeResult(
            observation=validated_status_observation(
                context,
                now=max(time.time(), now),
                outcome="error",
                reason_code="probe_failed",
                diagnostic="usage probe output exceeded the bound",
            )
        )
    return UsageProbeResult(
        observation=_observation_from_worker_stdout(
            context, stdout, stderr=stderr, now=now
        )
    )


def _observation_from_worker_stdout(
    context: UsageProbeContext, stdout: bytes, *, stderr: bytes = b"", now: float
) -> dict[str, Any]:
    clock = max(time.time(), now)
    if not stdout.strip():
        diagnostic = _worker_stderr_diagnostic(stderr)
        return validated_status_observation(
            context,
            now=clock,
            outcome="error",
            reason_code="probe_failed",
            diagnostic=diagnostic,
        )
    try:
        decoded = json.loads(stdout.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return validated_status_observation(
            context,
            now=clock,
            outcome="error",
            reason_code="parse_error",
        )
    if not isinstance(decoded, dict):
        return validated_status_observation(
            context,
            now=clock,
            outcome="error",
            reason_code="malformed_payload",
        )
    try:
        return validate_observation(
            _bind_observation(decoded, context, clock), now=clock
        )
    except (TypeError, ValueError, AttributeError):
        return validated_status_observation(
            context,
            now=clock,
            outcome="error",
            reason_code="malformed_payload",
        )


def _bind_observation(
    raw: Mapping[str, Any], context: UsageProbeContext, now: float
) -> dict[str, Any]:
    payload = dict(raw)
    payload.setdefault("schema_version", context.schema_version)
    payload.setdefault("provider", context.provider)
    payload.setdefault("context_id", context.context_id)
    payload.setdefault("account_generation", context.account_generation)
    payload.setdefault("ordering_token", context.request_started_at)
    payload.setdefault("received_at", max(now, context.request_started_at))
    payload.setdefault("source", "probe")
    payload.setdefault("authoritative_empty", False)
    return payload


def _worker_stderr_diagnostic(stderr: bytes) -> str | None:
    if not stderr:
        return None
    snippet = _first_nonempty_stderr_line(stderr)
    if not snippet:
        return None
    return bounded_probe_diagnostic(f"usage probe worker stderr: {snippet}")


def _first_nonempty_stderr_line(stderr: bytes) -> str:
    text = stderr.decode("utf-8", errors="replace")
    for line in text.splitlines():
        stripped = line.strip()
        if stripped:
            return stripped
    return ""


def _log_worker_stderr(provider: str, stderr: bytes, *, stdout: bytes) -> None:
    if not stderr:
        return
    if not stdout.strip():
        diagnostic = _worker_stderr_diagnostic(stderr)
        if diagnostic:
            log.warning(
                "usage probe worker stderr for provider %r: %s",
                provider,
                diagnostic,
            )
            return
    log.debug(
        "usage probe worker stderr for provider %r (%s bytes)",
        provider,
        len(stderr),
    )


def _env_allowed(name: str) -> bool:
    upper = name.upper()
    if any(marker in upper for marker in _DENIED_ENV_MARKERS) and not upper.endswith(
        "_PATH"
    ):
        return False
    if upper in _ALLOWED_ENV_NAMES:
        return True
    return any(upper.startswith(prefix) for prefix in _ALLOWED_ENV_PREFIXES)
