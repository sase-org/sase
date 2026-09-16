"""Wire records for the Ctrl+K prompt-history project filter.

The compiled-query / seed / batch-match contract is owned by
``sase_core_rs``. Python keeps typed dataclasses at the facade boundary so
TUI/history code does not depend on raw cross-language dicts.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

PROMPT_HISTORY_FILTER_WIRE_SCHEMA_VERSION = 1


@dataclass(frozen=True)
class PromptHistoryProjectIdentity:
    """One catalog entry describing a known project's identity."""

    key: str
    label: str | None = None
    aliases: list[str] = field(default_factory=list)
    raw_refs: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Return the ``sase_core_rs``-facing dict for this entry."""
        return {
            "key": self.key,
            "label": self.label,
            "aliases": list(self.aliases),
            "raw_refs": list(self.raw_refs),
        }


@dataclass(frozen=True)
class CompiledPromptHistoryQuery:
    """One compiled ``project:<value>`` + literal-text prompt-history query."""

    schema_version: int
    raw_project_value: str | None
    project_key: str | None
    project_label: str | None
    text: str
    valid: bool
    diagnostic: str | None

    @property
    def has_project_scope(self) -> bool:
        """Return whether the query carries any ``project:`` qualifier."""
        return self.raw_project_value is not None

    def to_dict(self) -> dict[str, Any]:
        """Return the ``sase_core_rs``-facing dict for this query."""
        return {
            "schema_version": self.schema_version,
            "raw_project_value": self.raw_project_value,
            "project_key": self.project_key,
            "project_label": self.project_label,
            "text": self.text,
            "valid": self.valid,
            "diagnostic": self.diagnostic,
        }


@dataclass(frozen=True)
class PromptHistoryRowFacts:
    """One loaded history row's pre-extracted facts for batch matching."""

    index: int
    canonical_text: str
    display_text: str
    segment_project_keys: list[str | None] = field(default_factory=list)
    segment_raw_refs: list[str | None] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Return the ``sase_core_rs``-facing dict for this row."""
        return {
            "index": self.index,
            "canonical_text": self.canonical_text,
            "display_text": self.display_text,
            "segment_project_keys": list(self.segment_project_keys),
            "segment_raw_refs": list(self.segment_raw_refs),
        }


@dataclass(frozen=True)
class PromptHistorySeed:
    """The initial Ctrl+K history query text plus an optional scope hint."""

    seed_text: str
    hint: str | None


def _optional_str(value: Any) -> str | None:
    return None if value is None else str(value)


def compiled_prompt_history_query_from_dict(
    data: dict[str, Any],
) -> CompiledPromptHistoryQuery:
    """Build :class:`CompiledPromptHistoryQuery` from a Rust wire dict."""
    return CompiledPromptHistoryQuery(
        schema_version=int(data["schema_version"]),
        raw_project_value=_optional_str(data.get("raw_project_value")),
        project_key=_optional_str(data.get("project_key")),
        project_label=_optional_str(data.get("project_label")),
        text=str(data["text"]),
        valid=bool(data["valid"]),
        diagnostic=_optional_str(data.get("diagnostic")),
    )


def prompt_history_seed_from_dict(data: dict[str, Any]) -> PromptHistorySeed:
    """Build :class:`PromptHistorySeed` from a Rust wire dict."""
    return PromptHistorySeed(
        seed_text=str(data["seed_text"]),
        hint=_optional_str(data.get("hint")),
    )


def prompt_history_match_result_indices(data: dict[str, Any]) -> frozenset[int]:
    """Return the matched row indices from a Rust match-result dict."""
    return frozenset(int(i) for i in data.get("matched_indices", []))


__all__ = [
    "PROMPT_HISTORY_FILTER_WIRE_SCHEMA_VERSION",
    "CompiledPromptHistoryQuery",
    "PromptHistoryProjectIdentity",
    "PromptHistoryRowFacts",
    "PromptHistorySeed",
    "compiled_prompt_history_query_from_dict",
    "prompt_history_match_result_indices",
    "prompt_history_seed_from_dict",
]
