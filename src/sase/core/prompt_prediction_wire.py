"""Wire records for the next-word prompt prediction engine.

The compile/predict contract is owned by ``sase_core_rs`` (frozen
``PromptPredictionCorpus`` / ``PromptPredictionModel`` handles in
``sase-core``'s ``prompt_prediction`` module). Python keeps typed frozen
dataclasses at the facade boundary so TUI/history code does not depend on
raw cross-language dicts. Every versioned record carries ``schema_version``
and every ``*_from_dict`` constructor rejects drift against
:data:`PROMPT_PREDICTION_WIRE_SCHEMA_VERSION`, following the
``prompt_history_filter`` style.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

PROMPT_PREDICTION_WIRE_SCHEMA_VERSION = 1

#: Source roles the Rust model accepts when composing corpora.
PROMPT_PREDICTION_SOURCE_ROLES = ("history", "session", "archive")


def _require_wire_schema(data: dict[str, Any], what: str) -> None:
    """Raise ``ValueError`` when *data* is stamped with a foreign schema."""
    schema = data.get("schema_version")
    if schema != PROMPT_PREDICTION_WIRE_SCHEMA_VERSION:
        raise ValueError(
            f"{what} has schema_version={schema!r}, expected "
            f"{PROMPT_PREDICTION_WIRE_SCHEMA_VERSION}"
        )


def _optional_str(value: Any) -> str | None:
    return None if value is None else str(value)


@dataclass(frozen=True)
class PromptPredictionRow:
    """One history row offered to the corpus compiler."""

    text: str
    epoch_seconds: int
    project: str | None = None
    origin: str | None = None
    cancelled: bool = False

    def to_dict(self) -> dict[str, Any]:
        """Return the ``sase_core_rs``-facing dict for this row."""
        return {
            "text": self.text,
            "epoch_seconds": self.epoch_seconds,
            "project": self.project,
            "origin": self.origin,
            "cancelled": self.cancelled,
        }


@dataclass(frozen=True)
class PromptPredictionCorpusOptions:
    """Compile options for one prompt prediction corpus."""

    schema_version: int = PROMPT_PREDICTION_WIRE_SCHEMA_VERSION
    now_epoch: int = 0
    recency_half_life_days: float = 14.0
    max_context_words: int = 4
    max_successors_per_context: int = 32
    prune_singleton_contexts: bool = False
    excluded_words: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Return the ``sase_core_rs``-facing dict for these options."""
        return {
            "schema_version": self.schema_version,
            "now_epoch": self.now_epoch,
            "recency_half_life_days": self.recency_half_life_days,
            "max_context_words": self.max_context_words,
            "max_successors_per_context": self.max_successors_per_context,
            "prune_singleton_contexts": self.prune_singleton_contexts,
            "excluded_words": list(self.excluded_words),
        }


@dataclass(frozen=True)
class PromptPredictionModelConfig:
    """Composition config for one prompt prediction model."""

    schema_version: int = PROMPT_PREDICTION_WIRE_SCHEMA_VERSION
    backoff_alpha: float = 0.4
    project_boost: float = 1.0
    draft_weight: float = 1.0
    reject_conflicts: bool = True

    def to_dict(self) -> dict[str, Any]:
        """Return the ``sase_core_rs``-facing dict for this config."""
        return {
            "schema_version": self.schema_version,
            "backoff_alpha": self.backoff_alpha,
            "project_boost": self.project_boost,
            "draft_weight": self.draft_weight,
            "reject_conflicts": self.reject_conflicts,
        }


@dataclass(frozen=True)
class PromptPredictionRequest:
    """One next-word prediction request for the text before the cursor."""

    text_before_cursor: str
    schema_version: int = PROMPT_PREDICTION_WIRE_SCHEMA_VERSION
    project: str | None = None
    limit: int = 5
    max_words: int = 4
    confidence: str = "balanced"
    include_draft: bool = True

    def to_dict(self) -> dict[str, Any]:
        """Return the ``sase_core_rs``-facing dict for this request."""
        return {
            "schema_version": self.schema_version,
            "text_before_cursor": self.text_before_cursor,
            "project": self.project,
            "limit": self.limit,
            "max_words": self.max_words,
            "confidence": self.confidence,
            "include_draft": self.include_draft,
        }


@dataclass(frozen=True)
class PromptPredictionSourceShares:
    """Per-source share of one candidate's combined mass at its best order."""

    history: float = 0.0
    project: float = 0.0
    session: float = 0.0
    draft: float = 0.0
    archive: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        """Return the ``sase_core_rs``-facing dict for these shares."""
        return {
            "history": self.history,
            "project": self.project,
            "session": self.session,
            "draft": self.draft,
            "archive": self.archive,
        }


def prompt_prediction_source_shares_from_dict(
    data: dict[str, Any],
) -> PromptPredictionSourceShares:
    """Build shares from a Rust wire dict (unversioned record)."""
    return PromptPredictionSourceShares(
        history=float(data.get("history", 0.0)),
        project=float(data.get("project", 0.0)),
        session=float(data.get("session", 0.0)),
        draft=float(data.get("draft", 0.0)),
        archive=float(data.get("archive", 0.0)),
    )


@dataclass(frozen=True)
class PromptPredictionCandidate:
    """One ranked next-word candidate with its gated continuation preview."""

    word: str
    key: str
    score: float
    probability: float
    support: int
    order: int
    source_shares: PromptPredictionSourceShares = field(
        default_factory=PromptPredictionSourceShares
    )
    continuation: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Return the ``sase_core_rs``-facing dict for this candidate."""
        return {
            "word": self.word,
            "key": self.key,
            "score": self.score,
            "probability": self.probability,
            "support": self.support,
            "order": self.order,
            "source_shares": self.source_shares.to_dict(),
            "continuation": list(self.continuation),
        }


def prompt_prediction_candidate_from_dict(
    data: dict[str, Any],
) -> PromptPredictionCandidate:
    """Build a candidate from a Rust wire dict (unversioned record)."""
    shares = data.get("source_shares") or {}
    return PromptPredictionCandidate(
        word=str(data["word"]),
        key=str(data["key"]),
        score=float(data["score"]),
        probability=float(data["probability"]),
        support=int(data["support"]),
        order=int(data["order"]),
        source_shares=prompt_prediction_source_shares_from_dict(dict(shares)),
        continuation=[str(word) for word in data.get("continuation", [])],
    )


@dataclass(frozen=True)
class PromptPredictionResult:
    """One next-word prediction result: gate verdict, ghost, and menu rows."""

    schema_version: int
    blocked_reason: str | None
    context_words: list[str] = field(default_factory=list)
    confident: bool = False
    ghost: list[str] = field(default_factory=list)
    candidates: list[PromptPredictionCandidate] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Return the ``sase_core_rs``-facing dict for this result."""
        return {
            "schema_version": self.schema_version,
            "blocked_reason": self.blocked_reason,
            "context_words": list(self.context_words),
            "confident": self.confident,
            "ghost": list(self.ghost),
            "candidates": [row.to_dict() for row in self.candidates],
        }


def prompt_prediction_result_from_dict(
    data: dict[str, Any],
) -> PromptPredictionResult:
    """Build a result from a Rust wire dict, rejecting schema drift."""
    _require_wire_schema(data, "PromptPredictionResult")
    return PromptPredictionResult(
        schema_version=int(data["schema_version"]),
        blocked_reason=_optional_str(data.get("blocked_reason")),
        context_words=[str(word) for word in data.get("context_words", [])],
        confident=bool(data.get("confident", False)),
        ghost=[str(word) for word in data.get("ghost", [])],
        candidates=[
            prompt_prediction_candidate_from_dict(dict(row))
            for row in data.get("candidates", [])
        ],
    )


@dataclass(frozen=True)
class PromptPrefixRankRequest:
    """One prefix-rank request for current-word completion."""

    text_before_word: str
    prefix: str
    schema_version: int = PROMPT_PREDICTION_WIRE_SCHEMA_VERSION
    project: str | None = None
    limit: int = 5

    def to_dict(self) -> dict[str, Any]:
        """Return the ``sase_core_rs``-facing dict for this request."""
        return {
            "schema_version": self.schema_version,
            "text_before_word": self.text_before_word,
            "prefix": self.prefix,
            "project": self.project,
            "limit": self.limit,
        }


@dataclass(frozen=True)
class PromptPrefixRankMatch:
    """One prefix-rank match with its model score and evidence order."""

    word: str
    key: str
    score: float
    order: int
    support: int

    def to_dict(self) -> dict[str, Any]:
        """Return the ``sase_core_rs``-facing dict for this match."""
        return {
            "word": self.word,
            "key": self.key,
            "score": self.score,
            "order": self.order,
            "support": self.support,
        }


def prompt_prefix_rank_match_from_dict(
    data: dict[str, Any],
) -> PromptPrefixRankMatch:
    """Build a match from a Rust wire dict (unversioned record)."""
    return PromptPrefixRankMatch(
        word=str(data["word"]),
        key=str(data["key"]),
        score=float(data["score"]),
        order=int(data["order"]),
        support=int(data["support"]),
    )


@dataclass(frozen=True)
class PromptPrefixRankResult:
    """One prefix-rank result: evidence context plus ranked matches."""

    schema_version: int
    context_words: list[str] = field(default_factory=list)
    matches: list[PromptPrefixRankMatch] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Return the ``sase_core_rs``-facing dict for this result."""
        return {
            "schema_version": self.schema_version,
            "context_words": list(self.context_words),
            "matches": [row.to_dict() for row in self.matches],
        }


def prompt_prefix_rank_result_from_dict(
    data: dict[str, Any],
) -> PromptPrefixRankResult:
    """Build a rank result from a Rust wire dict, rejecting schema drift."""
    _require_wire_schema(data, "PromptPrefixRankResult")
    return PromptPrefixRankResult(
        schema_version=int(data["schema_version"]),
        context_words=[str(word) for word in data.get("context_words", [])],
        matches=[
            prompt_prefix_rank_match_from_dict(dict(row))
            for row in data.get("matches", [])
        ],
    )


@dataclass(frozen=True)
class PromptPredictionCorpusStats:
    """Compile statistics for one frozen prediction corpus."""

    schema_version: int
    rows_used: int
    rows_generated_skipped: int
    rows_duplicate_skipped: int
    tokens: int
    contexts: int
    successor_entries: int
    approx_bytes: int

    def to_dict(self) -> dict[str, Any]:
        """Return the ``sase_core_rs``-facing dict for these stats."""
        return {
            "schema_version": self.schema_version,
            "rows_used": self.rows_used,
            "rows_generated_skipped": self.rows_generated_skipped,
            "rows_duplicate_skipped": self.rows_duplicate_skipped,
            "tokens": self.tokens,
            "contexts": self.contexts,
            "successor_entries": self.successor_entries,
            "approx_bytes": self.approx_bytes,
        }


def prompt_prediction_corpus_stats_from_dict(
    data: dict[str, Any],
) -> PromptPredictionCorpusStats:
    """Build stats from a Rust wire dict, rejecting schema drift."""
    _require_wire_schema(data, "PromptPredictionCorpusStats")
    return PromptPredictionCorpusStats(
        schema_version=int(data["schema_version"]),
        rows_used=int(data["rows_used"]),
        rows_generated_skipped=int(data["rows_generated_skipped"]),
        rows_duplicate_skipped=int(data["rows_duplicate_skipped"]),
        tokens=int(data["tokens"]),
        contexts=int(data["contexts"]),
        successor_entries=int(data["successor_entries"]),
        approx_bytes=int(data["approx_bytes"]),
    )


__all__ = [
    "PROMPT_PREDICTION_WIRE_SCHEMA_VERSION",
    "PROMPT_PREDICTION_SOURCE_ROLES",
    "PromptPredictionRow",
    "PromptPredictionCorpusOptions",
    "PromptPredictionModelConfig",
    "PromptPredictionRequest",
    "PromptPredictionSourceShares",
    "PromptPredictionCandidate",
    "PromptPredictionResult",
    "PromptPrefixRankRequest",
    "PromptPrefixRankMatch",
    "PromptPrefixRankResult",
    "PromptPredictionCorpusStats",
    "prompt_prediction_source_shares_from_dict",
    "prompt_prediction_candidate_from_dict",
    "prompt_prediction_result_from_dict",
    "prompt_prefix_rank_match_from_dict",
    "prompt_prefix_rank_result_from_dict",
    "prompt_prediction_corpus_stats_from_dict",
]
