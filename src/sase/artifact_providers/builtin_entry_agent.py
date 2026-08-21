"""Python-owned entry-property enrichment for ``@agent``.

Resolution itself is unchanged: it still delegates to the Rust resolver,
which already globalizes the agent name and finds ``agents/<name>/README.md``.
This module only adds the structured :class:`ArtifactEntry` properties read
from the resolved page's own directory. Staging still retains that published
page; prompt expansion names the agent without a filesystem path.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from sase.artifact_providers.builtin_entries import (
    BuiltinEntryOutcome,
    validate_builtin_entry,
)
from sase.artifact_ref_models import ArtifactEntry, ArtifactRef, ArtifactRefContext
from sase.artifact_ref_operations import resolve_artifact_ref
from sase.artifact_ref_prompt_context import PromptRefContext


log = logging.getLogger(__name__)


def resolve_agent_entry(
    reference: ArtifactRef,
    *,
    context: ArtifactRefContext,
    ref_context: PromptRefContext,
) -> BuiltinEntryOutcome:
    resolution = resolve_artifact_ref(reference, context=context)
    entry = None
    if resolution.resolved_path is not None:
        entry = _agent_entry(reference.payload.name or "", resolution.resolved_path)
    return BuiltinEntryOutcome(
        status=resolution.status,
        entry=entry,
        locator=resolution.locator,
        resolved_path=resolution.resolved_path,
        candidates=resolution.candidates,
        diagnostic=resolution.diagnostic,
        # Resolution globalizes a bare local name (e.g. "9w" -> "alice.athena.9w");
        # carry that canonical spelling since it differs from what was typed.
        canonical_reference=resolution.rendered,
    )


def _agent_entry(name: str, resolved_path: Path) -> ArtifactEntry | None:
    page_dir = resolved_path.parent
    properties: dict[str, str] = {}
    _add_meta_properties(page_dir / "meta.json", properties)
    _add_state_properties(page_dir / "state.json", properties)

    try:
        from sase.sase_agent import sase_agent_name

        # ``lane`` is the serialized compatibility key for the sase-agent name.
        properties["lane"] = sase_agent_name(name)
    except Exception:
        log.debug("Unable to derive sase-agent name for %r", name, exc_info=True)

    return validate_builtin_entry(
        ArtifactEntry(
            stable_id=f"agent:{name}",
            ref_kind="agent",
            canonical_argument=name,
            display_label=name,
            origin="prompt_ref",
            project_display_name=properties.get("project"),
            properties=properties,
        )
    )


def _add_meta_properties(path: Path, properties: dict[str, str]) -> None:
    try:
        from sase.agents_sync.v2_run_io import run_metadata_from_json

        raw = json.loads(path.read_text(encoding="utf-8"))
        metadata = run_metadata_from_json(raw)
    except Exception:
        log.debug("Unable to read agent metadata from %s", path, exc_info=True)
        return
    properties["project"] = metadata.project.name
    properties["agent"] = metadata.local_name
    extra = dict(metadata.metadata)
    for key in ("model", "llm_provider"):
        value = extra.get(key)
        if isinstance(value, str) and value:
            properties[key] = value
    tribe = extra.get("tribe") or extra.get("clan_tribe")
    if isinstance(tribe, str) and tribe:
        properties["tribe"] = tribe


def _add_state_properties(path: Path, properties: dict[str, str]) -> None:
    try:
        from sase.agents_sync.v2_run_io import run_state_from_json

        raw = json.loads(path.read_text(encoding="utf-8"))
        state = run_state_from_json(raw)
    except Exception:
        log.debug("Unable to read agent state from %s", path, exc_info=True)
        return
    properties["state"] = state.state
    if state.started_at:
        properties["started_at"] = state.started_at
    if state.finished_at:
        properties["finished_at"] = state.finished_at


__all__ = ["resolve_agent_entry"]
