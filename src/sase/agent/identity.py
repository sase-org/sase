"""Shared SASE agent identity discovery helpers."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
import json
import logging
import os
from pathlib import Path
from typing import Literal

_logger = logging.getLogger(__name__)

AgentIdentitySource = Literal["SASE_AGENT_NAME", "agent_meta"]


class AgentIdentityError(ValueError):
    """Raised when an auditable agent identity cannot be found."""


@dataclass(frozen=True)
class AgentIdentity:
    """Attributable SASE agent identity for audited commands."""

    name: str
    source: AgentIdentitySource
    artifacts_dir: str | None = None


def discover_agent_identity(
    env: Mapping[str, str] | None = None,
) -> AgentIdentity | None:
    """Discover the current agent identity from environment and metadata."""
    current_env = env if env is not None else os.environ
    artifacts_dir = _clean_value(current_env.get("SASE_ARTIFACTS_DIR"))

    env_name = _clean_value(current_env.get("SASE_AGENT_NAME"))
    if env_name is not None:
        return AgentIdentity(
            name=env_name,
            source="SASE_AGENT_NAME",
            artifacts_dir=artifacts_dir,
        )

    meta_name = agent_name_from_meta(artifacts_dir)
    if meta_name is None:
        return None
    return AgentIdentity(
        name=meta_name,
        source="agent_meta",
        artifacts_dir=artifacts_dir,
    )


def require_agent_identity(
    env: Mapping[str, str] | None = None,
    *,
    purpose: str = "auditable agent actions",
) -> AgentIdentity:
    """Return the current agent identity or raise a clear auditability error."""
    identity = discover_agent_identity(env)
    if identity is None:
        raise AgentIdentityError(
            f"{purpose} require agent attribution; set SASE_AGENT_NAME, "
            "or provide SASE_ARTIFACTS_DIR/agent_meta.json with a name"
        )
    return identity


def resolve_local_agent_name(env: Mapping[str, str] | None = None) -> str | None:
    """Resolve the current locally stored SASE agent name, if available.

    Unlike :func:`discover_agent_identity`, this resolver is metadata-first:
    family members can replace one another inside a single process, leaving
    ``SASE_AGENT_NAME`` set to the lane while this run's ``agent_meta.json``
    carries the concrete member. Only the metadata ``name`` key is consulted,
    so commit provenance keeps its narrow behavior.
    """
    current_env = env if env is not None else os.environ
    meta = _agent_meta_from_dir(_clean_value(current_env.get("SASE_ARTIFACTS_DIR")))
    if meta is not None:
        raw_name = meta.get("name")
        if isinstance(raw_name, str):
            meta_name = _clean_value(raw_name)
            if meta_name is not None:
                return meta_name
    return _clean_value(current_env.get("SASE_AGENT_NAME"))


def discover_agent_runtime(
    env: Mapping[str, str] | None = None,
    *,
    artifacts_dir: str | None = None,
) -> str | None:
    """Best-effort runtime/provider discovery for audited agent commands."""
    current_env = env if env is not None else os.environ
    for key in ("SASE_AGENT_LLM_PROVIDER", "SASE_LLM_PROVIDER", "SASE_AGENT_PROVIDER"):
        value = _clean_value(current_env.get(key))
        if value is not None:
            return value

    meta_artifacts_dir = _clean_value(artifacts_dir) or _clean_value(
        current_env.get("SASE_ARTIFACTS_DIR")
    )
    meta = _agent_meta_from_dir(meta_artifacts_dir)
    if meta is None:
        return None

    for key in ("llm_provider", "provider", "runtime"):
        raw_value = meta.get(key)
        if isinstance(raw_value, str):
            cleaned = _clean_value(raw_value)
            if cleaned is not None:
                return cleaned

    model = meta.get("model")
    if isinstance(model, str):
        cleaned = _clean_value(model)
        if cleaned and "/" in cleaned:
            provider, _, _ = cleaned.partition("/")
            return _clean_value(provider)
    return None


def resolve_observation_window_start(env: Mapping[str, str] | None = None) -> str:
    """Resolve the caller's observation-window start for a task ``+1``.

    A SASE agent's window opens when its run began, read from its own
    ``agent_meta.json``; a human filing a ``+1`` is asserting it now, so a
    human's window is the current time. Missing or malformed agent metadata
    falls back to the current time rather than failing the command.
    """
    identity = discover_agent_identity(env)
    if identity is None:
        return current_instant()
    meta = _agent_meta_from_dir(identity.artifacts_dir)
    if meta is None:
        _logger.debug(
            "observation window: no readable agent_meta.json for %s; "
            "falling back to the current time",
            identity.name,
        )
        return current_instant()
    run_started_at = meta.get("run_started_at")
    if not isinstance(run_started_at, str) or not run_started_at.strip():
        _logger.debug(
            "observation window: agent_meta.json for %s has no "
            "run_started_at; falling back to the current time",
            identity.name,
        )
        return current_instant()
    return run_started_at


def current_instant() -> str:
    """Return the current UTC instant as an RFC 3339 timestamp.

    Sub-second precision matters here: bead timestamps like ``closed_at``
    are truncated to whole seconds, so an instant computed in the same
    wall-clock second as a close must still resolve strictly after it, and
    only a fractional part guarantees that.
    """
    return datetime.now(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _clean_value(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


def agent_name_from_meta(artifacts_dir: str | None) -> str | None:
    meta = _agent_meta_from_dir(artifacts_dir)
    if meta is None:
        return None
    for key in ("name", "workflow_name", "agent_name"):
        value = meta.get(key)
        if isinstance(value, str):
            cleaned = _clean_value(value)
            if cleaned is not None:
                return cleaned
    return None


def _agent_meta_from_dir(artifacts_dir: str | None) -> Mapping[str, object] | None:
    if artifacts_dir is None:
        return None
    meta_path = Path(artifacts_dir).expanduser() / "agent_meta.json"
    try:
        data = json.loads(meta_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(data, Mapping):
        return None
    return data


__all__ = [
    "AgentIdentity",
    "AgentIdentityError",
    "AgentIdentitySource",
    "agent_name_from_meta",
    "current_instant",
    "discover_agent_identity",
    "discover_agent_runtime",
    "require_agent_identity",
    "resolve_local_agent_name",
    "resolve_observation_window_start",
]
