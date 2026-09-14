"""Prompt projection: discovering and applying reducible-span replacements."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from sase.llm_provider.continuation_budget_spans import extract_reducible_spans

_OMISSION_MESSAGES = {
    "newest_diagnostics": (
        "Selected diagnostics omitted by continuation budget; "
        "use the evidence refs and monitor retrieval command above."
    ),
    "old_raw_excerpts": (
        "Raw output excerpt omitted by continuation budget; "
        "use the retained log refs or monitor retrieval command above."
    ),
    "checkpoint": (
        "Pre-checkpoint assistant transcript omitted by continuation "
        "budget; the checkpoint in this block preserves the current "
        "objective, constraints, findings, and remaining work."
    ),
}


@dataclass(frozen=True, slots=True)
class _PromptReplacement:
    kind: str
    start: int
    end: int
    replacement: str
    checkpoint_ref: str | None = None
    covered_node_ids: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class PromptProjection:
    rendered_prompt_bytes: int
    essential_bytes: int
    selected_evidence_bytes: int
    candidates: tuple[dict[str, Any], ...]
    replacements_by_kind: Mapping[str, tuple[_PromptReplacement, ...]]


def prompt_projection(prompt: str) -> PromptProjection:
    replacements = _discover_replacements(prompt)
    by_kind: dict[str, list[_PromptReplacement]] = {}
    for replacement in replacements:
        saved = _replacement_saved_bytes(prompt, replacement)
        if saved <= 0:
            continue
        by_kind.setdefault(replacement.kind, []).append(replacement)

    candidates: list[dict[str, Any]] = []
    reducible_bytes = 0
    selected_evidence_bytes = 0
    replacements_by_kind: dict[str, tuple[_PromptReplacement, ...]] = {}
    for kind, items in by_kind.items():
        replacements_by_kind[kind] = tuple(items)
        bytes_saved = sum(_replacement_saved_bytes(prompt, item) for item in items)
        reducible_bytes += bytes_saved
        if kind in {"old_raw_excerpts", "newest_diagnostics"}:
            selected_evidence_bytes += bytes_saved
        candidate: dict[str, Any] = {
            "kind": kind,
            "bytes": bytes_saved,
        }
        checkpoint_refs = [item.checkpoint_ref for item in items if item.checkpoint_ref]
        if checkpoint_refs:
            candidate["checkpoint_ref"] = checkpoint_refs[0]
        covered = sorted(
            {node_id for item in items for node_id in item.covered_node_ids if node_id}
        )
        if covered:
            candidate["covered_node_ids"] = covered
        candidates.append(candidate)

    rendered_bytes = utf8_len(prompt)
    return PromptProjection(
        rendered_prompt_bytes=rendered_bytes,
        essential_bytes=max(0, rendered_bytes - reducible_bytes),
        selected_evidence_bytes=selected_evidence_bytes,
        candidates=tuple(candidates),
        replacements_by_kind=replacements_by_kind,
    )


def _discover_replacements(prompt: str) -> list[_PromptReplacement]:
    """Discover reducible spans the render layer explicitly marked.

    Discovery never guesses from Markdown headings: an authored or
    untrusted heading string like ``## Selected diagnostics`` is not
    evidence of a genuinely reducible section, only the render-emitted
    marker pair around it is. See ``continuation_budget_spans``.
    """

    replacements: list[_PromptReplacement] = []
    for span in extract_reducible_spans(prompt):
        message = _OMISSION_MESSAGES.get(span.kind)
        if message is None:
            continue
        replacements.append(
            _PromptReplacement(
                kind=span.kind,
                start=span.start,
                end=span.end,
                replacement=f"_{message}_\n",
                checkpoint_ref=span.checkpoint_ref,
                covered_node_ids=span.covered_node_ids,
            )
        )
    return replacements


def project_prompt(
    prompt: str,
    decision: Mapping[str, Any],
    projection: PromptProjection,
) -> str:
    if str(decision.get("kind") or "") != "compact":
        return prompt
    selected_kinds = [
        str(item.get("kind"))
        for item in decision.get("reductions", [])
        if isinstance(item, Mapping) and item.get("kind")
    ]
    replacements: list[_PromptReplacement] = []
    for kind in selected_kinds:
        replacements.extend(projection.replacements_by_kind.get(kind, ()))
    if not replacements:
        return prompt
    return _apply_replacements(prompt, replacements)


def _apply_replacements(
    prompt: str,
    replacements: list[_PromptReplacement],
) -> str:
    selected: list[_PromptReplacement] = []
    last_end = 0
    for replacement in sorted(replacements, key=lambda item: (item.start, item.end)):
        if replacement.start < last_end:
            continue
        selected.append(replacement)
        last_end = replacement.end
    parts: list[str] = []
    cursor = 0
    for replacement in selected:
        parts.append(prompt[cursor : replacement.start])
        parts.append(replacement.replacement)
        cursor = replacement.end
    parts.append(prompt[cursor:])
    return "".join(parts)


def _replacement_saved_bytes(
    prompt: str,
    replacement: _PromptReplacement,
) -> int:
    return max(
        0,
        utf8_len(prompt[replacement.start : replacement.end])
        - utf8_len(replacement.replacement),
    )


def utf8_len(text: str) -> int:
    return len(text.encode("utf-8", errors="replace"))
