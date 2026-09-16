"""Thin facade over the ``sase_core_rs`` prompt-history project filter."""

from __future__ import annotations

from sase.core.prompt_history_filter_wire import (
    CompiledPromptHistoryQuery,
    PromptHistoryProjectIdentity,
    PromptHistoryRowFacts,
    PromptHistorySeed,
    compiled_prompt_history_query_from_dict,
    prompt_history_match_result_indices,
    prompt_history_seed_from_dict,
)
from sase.core.rust import require_rust_binding


def compile_prompt_history_query(
    raw_query: str,
    catalog: list[PromptHistoryProjectIdentity],
) -> CompiledPromptHistoryQuery:
    """Compile one Ctrl+K filter string via ``sase_core_rs``."""
    binding = require_rust_binding("compile_prompt_history_query")
    payload = binding(raw_query, [entry.to_dict() for entry in catalog])
    return compiled_prompt_history_query_from_dict(dict(payload))


def build_prompt_history_seed(
    *,
    raw_ref: str | None,
    remainder_text: str,
    catalog: list[PromptHistoryProjectIdentity],
) -> PromptHistorySeed:
    """Build the initial Ctrl+K history query via ``sase_core_rs``."""
    binding = require_rust_binding("build_prompt_history_seed")
    payload = binding(
        {"raw_ref": raw_ref, "remainder_text": remainder_text},
        [entry.to_dict() for entry in catalog],
    )
    return prompt_history_seed_from_dict(dict(payload))


def match_prompt_history_rows(
    query: CompiledPromptHistoryQuery,
    rows: list[PromptHistoryRowFacts],
) -> frozenset[int]:
    """Return the indices of *rows* matching *query* via ``sase_core_rs``."""
    binding = require_rust_binding("match_prompt_history_rows")
    payload = binding(query.to_dict(), [row.to_dict() for row in rows])
    return prompt_history_match_result_indices(dict(payload))


__all__ = [
    "build_prompt_history_seed",
    "compile_prompt_history_query",
    "match_prompt_history_rows",
]
