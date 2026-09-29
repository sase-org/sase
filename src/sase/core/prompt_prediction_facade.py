"""Thin adapter over the ``sase_core_rs`` prompt prediction handles.

All tokenizing, compiling, scoring, gating, and continuation logic lives in
sase-core (``crates/sase_core/src/prompt_prediction/``). This module only
compiles frozen Rust handles off the event loop and exposes typed views
over the dicts they return.

A corpus is built once from history rows; a model cheaply composes frozen
corpora (history, session, archive) plus config and answers per-keystroke
``predict`` / ``rank_prefix`` queries. Rebuild the model (not the corpora)
whenever any corpus swaps.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Final

from sase.core.prompt_prediction_wire import (
    PROMPT_PREDICTION_SOURCE_ROLES,
    PROMPT_PREDICTION_WIRE_SCHEMA_VERSION,
    PromptPredictionCorpusOptions,
    PromptPredictionCorpusStats,
    PromptPredictionModelConfig,
    PromptPredictionReplayOptions,
    PromptPredictionReplayReport,
    PromptPredictionRequest,
    PromptPredictionRow,
    PromptPrefixRankRequest,
    PromptPredictionResult,
    PromptPrefixRankResult,
    prompt_prediction_corpus_stats_from_dict,
    prompt_prediction_replay_report_from_dict,
    prompt_prediction_result_from_dict,
    prompt_prefix_rank_result_from_dict,
)

PROMPT_PREDICTION_SCHEMA_VERSION: Final = PROMPT_PREDICTION_WIRE_SCHEMA_VERSION


def _check_handle_schema(handle: Any, what: str) -> None:
    """Raise ``RuntimeError`` when a Rust handle drifts from this checkout."""
    if handle.SCHEMA_VERSION != PROMPT_PREDICTION_SCHEMA_VERSION:
        raise RuntimeError(
            f"{what} schema mismatch: rust "
            f"{handle.SCHEMA_VERSION} != "
            f"python {PROMPT_PREDICTION_SCHEMA_VERSION}"
        )


@dataclass(frozen=True, slots=True)
class PromptPredictionCorpus:
    """A frozen ``sase_core_rs.PromptPredictionCorpus`` handle."""

    _handle: Any

    @classmethod
    def compile(
        cls,
        rows: Sequence[PromptPredictionRow],
        options: PromptPredictionCorpusOptions,
    ) -> PromptPredictionCorpus:
        """Compile *rows* into a frozen corpus with *options*.

        Call only from a worker thread: compile parses every row and
        releases the GIL while the Rust core counts n-grams.
        """
        from sase.core.rust import require_rust_binding

        handle = require_rust_binding("PromptPredictionCorpus")(
            json.dumps([row.to_dict() for row in rows]),
            json.dumps(options.to_dict()),
        )
        _check_handle_schema(handle, "PromptPredictionCorpus")
        return cls(_handle=handle)

    def stats(self) -> PromptPredictionCorpusStats:
        """Return compile statistics for this corpus."""
        return prompt_prediction_corpus_stats_from_dict(dict(self._handle.stats()))

    def __len__(self) -> int:
        return len(self._handle)


@dataclass(frozen=True, slots=True)
class PromptPredictionModel:
    """A composed ``sase_core_rs.PromptPredictionModel`` handle."""

    _handle: Any

    @classmethod
    def compose(
        cls,
        sources: Sequence[tuple[PromptPredictionCorpus, str, float]],
        config: PromptPredictionModelConfig,
    ) -> PromptPredictionModel:
        """Compose a model from ``(corpus, role, weight)`` sources.

        *role* is one of ``history``, ``session``, or ``archive``.
        """
        from sase.core.rust import require_rust_binding

        for _, role, _ in sources:
            if role not in PROMPT_PREDICTION_SOURCE_ROLES:
                raise ValueError(f"unknown prompt prediction source role: {role!r}")
        handle = require_rust_binding("PromptPredictionModel")(
            [(corpus._handle, role, weight) for corpus, role, weight in sources],
            json.dumps(config.to_dict()),
        )
        _check_handle_schema(handle, "PromptPredictionModel")
        return cls(_handle=handle)

    def predict(self, request: PromptPredictionRequest) -> PromptPredictionResult:
        """Predict next words for the text before the cursor."""
        return prompt_prediction_result_from_dict(
            dict(self._handle.predict(json.dumps(request.to_dict())))
        )

    def rank_prefix(self, request: PromptPrefixRankRequest) -> PromptPrefixRankResult:
        """Rank current-word completions for a typed prefix."""
        return prompt_prefix_rank_result_from_dict(
            dict(self._handle.rank_prefix(json.dumps(request.to_dict())))
        )


# symvision: tools/prompt_prediction_replay
def evaluate_prompt_prediction_replay(
    rows: Sequence[PromptPredictionRow],
    options: PromptPredictionReplayOptions,
) -> PromptPredictionReplayReport:
    """Run a prequential replay over *rows* with *options*.

    Warms on the oldest share of typed rows, scores every word-boundary
    position of each later row, then sweeps preset and grid thresholds
    without replaying. The report holds aggregates only, never prompt
    text. Call only from a worker thread: replay parses every row and
    releases the GIL while the Rust core scores positions.
    """
    from sase.core.rust import require_rust_binding

    evaluate = require_rust_binding("evaluate_prompt_prediction_replay")
    return prompt_prediction_replay_report_from_dict(
        dict(
            evaluate(
                json.dumps([row.to_dict() for row in rows]),
                json.dumps(options.to_dict()),
            )
        )
    )


__all__ = [
    "PROMPT_PREDICTION_SCHEMA_VERSION",
    "PromptPredictionCorpus",
    "PromptPredictionModel",
    "evaluate_prompt_prediction_replay",
]
