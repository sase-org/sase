"""Derive `agent cites plan` rows from the plan/prompt header-block chain."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path, PurePosixPath
from typing import Any

from sase.agents_sync.prompt_archive.paths import prompt_document_path
from sase.artifact_links.derive._model import DerivableDocument, DerivedLinkCandidate
from sase.sdd.plan_header_block import PlanHeaderSectionKind, parse_plan_header_block

_PLAN_KIND = "plan"


def derive_agent_cites_plan(
    document: DerivableDocument,
    *,
    agents_sidecar_root: Path | None,
    is_agent_published: Callable[[str], bool],
) -> tuple[DerivedLinkCandidate, ...]:
    """Emit `agent:<name> cites plan:<relpath>` from two header blocks.

    Walks *document*'s own canonical `PROMPT:` section to its archived
    prompt, then that prompt's own canonical `AGENTS:` section for the
    agents that consumed it -- both Rust-owned, machine-parsed header
    sections, never prose, and never the plan's own `AGENTS`/`COMMITS`
    sections. Skips silently rather than writing a dangling or premature
    row: a non-plan ref, no agents sidecar clone, unreadable or unparseable
    content, no canonical `PROMPT:` section, a missing archived prompt, and
    any agent whose ref does not resolve as published (owner decision 5)
    all contribute no candidate.
    """

    kind, _, _ = document.ref.partition(":")
    if kind != _PLAN_KIND or agents_sidecar_root is None:
        return ()
    parsed = _parse_header_block(document.path)
    if parsed is None:
        return ()
    prompt_label = next(
        (
            section.label
            for section in parsed.sections
            if section.kind is PlanHeaderSectionKind.PROMPT and section.label
        ),
        None,
    )
    if prompt_label is None:
        return ()
    prompt_path = _resolve_prompt_path(agents_sidecar_root, prompt_label)
    if prompt_path is None:
        return ()
    prompt_parsed = _parse_header_block(prompt_path)
    if prompt_parsed is None:
        return ()
    agent_names = dict.fromkeys(
        entry.label
        for section in prompt_parsed.sections
        if section.kind is PlanHeaderSectionKind.AGENTS
        for entry in section.entries
        if entry.label
    )
    return tuple(
        DerivedLinkCandidate(
            source_ref=f"agent:{name}",
            relation="cites",
            target_ref=document.ref,
            description=(
                f"derived from {prompt_label}'s `AGENTS:` header entry for {name}"
            ),
        )
        for name in agent_names
        if is_agent_published(name)
    )


def _parse_header_block(path: Path) -> Any:
    try:
        content = path.read_text(encoding="utf-8")
    except OSError:
        return None
    try:
        return parse_plan_header_block(content)
    except Exception:  # noqa: BLE001 - a malformed header yields no candidate.
        return None


def _resolve_prompt_path(agents_sidecar_root: Path, label: str) -> Path | None:
    raw = label.strip().removeprefix("./")
    parts = PurePosixPath(raw).parts
    if len(parts) != 3 or parts[0] != "prompts":
        return None
    try:
        path = prompt_document_path(agents_sidecar_root, parts[1], parts[2])
    except ValueError:
        return None
    return path if path.is_file() else None


__all__ = ["derive_agent_cites_plan"]
