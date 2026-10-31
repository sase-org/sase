"""Shared helpers for pipe-marker adoption.

Public names in this private module are shared by the pipe split
(``run_agent_exec_pipe_*``). Helpers needed by only one pipe module
live in that module instead.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from sase.agent.staged_handoff import successor_prompt_digest
from sase.axe.run_agent_exec_plan_accept_models import (
    resolve_model_alias_provenance,
    resolve_model_meta,
)
from sase.axe.run_agent_successor import FollowupModel
from sase.llm_provider.config import (
    format_model_directive_value,
    normalize_model_alias_reference,
)


def build_pipe_successor_prompt(
    piped_prompt: str,
    *,
    parent_name: str | None,
    fresh: bool,
    model_prefix: str = "",
) -> str:
    """Assemble the successor prompt: model, optional fork, then piped text."""
    parts: list[str] = []
    if model_prefix:
        prefix = model_prefix if model_prefix.endswith("\n") else f"{model_prefix}\n"
        parts.append(prefix)
    if not fresh and parent_name:
        parts.append(f"#fork:{parent_name}\n")
    parts.append(piped_prompt)
    return "".join(parts)


def resolve_pipe_model(model_spec: str) -> FollowupModel:
    directive = format_model_directive_value(model_spec)
    model_alias, _ = normalize_model_alias_reference(directive)
    trail, origin = resolve_model_alias_provenance(directive)
    return FollowupModel(
        model_prefix=f"%model:{directive}\n",
        meta=resolve_model_meta(directive),
        model_alias=model_alias,
        model_alias_trail=trail,
        model_alias_origin=origin,
    )


def interrupted_phase_meta(
    artifacts_dir: str,
    fallback_meta: dict[str, Any],
) -> dict[str, Any]:
    meta_path = Path(artifacts_dir) / "agent_meta.json"
    try:
        loaded = json.loads(meta_path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return fallback_meta
    return loaded if isinstance(loaded, dict) and loaded else fallback_meta


def pipe_depth(pipe_data: dict[str, Any], base_meta: dict[str, Any]) -> int:
    for source in (pipe_data, base_meta):
        raw = source.get("pipe_depth")
        if type(raw) is int and raw >= 0:
            return raw
    return 0


def read_successor_prompt(successor: Mapping[str, Any]) -> str:
    path = Path(str(successor["prompt_ref"]))
    prompt = path.read_text(encoding="utf-8")
    if successor.get("prompt_digest") != successor_prompt_digest(prompt):
        raise RuntimeError("persisted pipe successor prompt digest does not match")
    return prompt


def read_json_meta(path: Path) -> dict[str, Any] | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, UnicodeError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def text(value: Any) -> str | None:
    return value if isinstance(value, str) and value else None


__all__ = [
    "build_pipe_successor_prompt",
    "interrupted_phase_meta",
    "pipe_depth",
    "read_json_meta",
    "read_successor_prompt",
    "resolve_pipe_model",
    "text",
]
