"""Redaction helpers for Agents-tab repro bundles."""

from __future__ import annotations

import hashlib
from dataclasses import replace
from pathlib import PurePosixPath, PureWindowsPath
from typing import Any

from .schema import (
    AgentIdentity,
    ReproAgentRow,
    ReproAppState,
    ReproBundle,
    ReproLoadStep,
    ReproSelectionFallback,
)

_BODY_KEYS = {
    "prompt",
    "prompt_body",
    "response",
    "response_body",
    "chat",
    "chat_body",
    "diff",
    "diff_body",
}


class RedactionContext:
    """Stable alias map for one bundle redaction pass."""

    def __init__(self, *, commit_safe: bool = True) -> None:
        self.commit_safe = commit_safe
        self._cl_aliases: dict[str, str] = {}

    def cl_name(self, value: str) -> str:
        if not self.commit_safe:
            return value
        alias = self._cl_aliases.get(value)
        if alias is None:
            alias = f"cl_{_digest(value)}"
            self._cl_aliases[value] = alias
        return alias

    def string(self, value: str) -> str:
        if not self.commit_safe:
            return value
        if _looks_path_like(value):
            return _shorten_path_like(value)
        return value


def redact_bundle(bundle: ReproBundle, *, commit_safe: bool = True) -> ReproBundle:
    """Return a bundle copy with shareable row and metadata values."""

    ctx = RedactionContext(commit_safe=commit_safe)
    return replace(
        bundle,
        load_steps=[_redact_load_step(step, ctx) for step in bundle.load_steps],
    )


def _redact_load_step(step: ReproLoadStep, ctx: RedactionContext) -> ReproLoadStep:
    return replace(
        step,
        agent_rows=[_redact_agent_row(row, ctx) for row in step.agent_rows],
        app_state=_redact_app_state(step.app_state, ctx),
        metadata=_redact_metadata(step.metadata, ctx),
    )


def _redact_agent_row(row: ReproAgentRow, ctx: RedactionContext) -> ReproAgentRow:
    metadata = _redact_metadata(row.metadata, ctx)
    return replace(
        row,
        cl_name=ctx.cl_name(row.cl_name),
        agent_name=None if ctx.commit_safe else row.agent_name,
        metadata=metadata,
    )


def _redact_app_state(state: ReproAppState, ctx: RedactionContext) -> ReproAppState:
    return replace(
        state,
        visible_identities=[
            _redact_identity(identity, ctx) for identity in state.visible_identities
        ],
        selected_identity=(
            None
            if state.selected_identity is None
            else _redact_identity(state.selected_identity, ctx)
        ),
        dismissed_identities=[
            _redact_identity(identity, ctx) for identity in state.dismissed_identities
        ],
        selection_fallback=_redact_selection_fallback(state.selection_fallback, ctx),
    )


def _redact_selection_fallback(
    fallback: ReproSelectionFallback | None,
    ctx: RedactionContext,
) -> ReproSelectionFallback | None:
    if fallback is None:
        return None
    return replace(
        fallback,
        from_identity=(
            None
            if fallback.from_identity is None
            else _redact_identity(fallback.from_identity, ctx)
        ),
        to_identity=(
            None
            if fallback.to_identity is None
            else _redact_identity(fallback.to_identity, ctx)
        ),
    )


def _redact_identity(identity: AgentIdentity, ctx: RedactionContext) -> AgentIdentity:
    agent_type, cl_name, raw_suffix = identity
    return (agent_type, ctx.cl_name(cl_name), raw_suffix)


def _redact_metadata(value: Any, ctx: RedactionContext) -> Any:
    """Redact nested JSON-like metadata defensively."""

    if isinstance(value, dict):
        redacted: dict[str, Any] = {}
        for key, item in value.items():
            key_text = str(key)
            if key_text in _BODY_KEYS or key_text.endswith("_body"):
                continue
            if "identity" in key_text and isinstance(item, list | tuple):
                redacted[key_text] = _redact_identity_like(item, ctx)
            else:
                redacted[key_text] = _redact_metadata(item, ctx)
        return redacted
    if isinstance(value, list):
        return [_redact_metadata(item, ctx) for item in value]
    if isinstance(value, tuple):
        return [_redact_metadata(item, ctx) for item in value]
    if isinstance(value, str):
        return ctx.string(value)
    return value


def _redact_identity_like(
    value: list[Any] | tuple[Any, ...], ctx: RedactionContext
) -> Any:
    if len(value) != 3 or not isinstance(value[1], str):
        return _redact_metadata(list(value), ctx)
    agent_type = value[0]
    raw_suffix = value[2]
    if agent_type not in ("run", "workflow") or not (
        raw_suffix is None or isinstance(raw_suffix, str)
    ):
        return _redact_metadata(list(value), ctx)
    return [agent_type, ctx.cl_name(value[1]), raw_suffix]


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:10]


def _looks_path_like(value: str) -> bool:
    if "/" in value or "\\" in value:
        return True
    return value.startswith("~")


def _shorten_path_like(value: str) -> str:
    path_cls = PureWindowsPath if "\\" in value else PurePosixPath
    path = path_cls(value)
    parts = [part for part in path.parts if part not in ("", "/", "\\")]
    if not parts:
        return "<path>"
    tail = "/".join(parts[-2:])
    return f"<path:{tail}>"
