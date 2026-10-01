"""Wire records for the next-word prompt prediction engine.

This module is the stable import path for the prompt prediction wire. The
definitions live in sibling modules to keep each file under the 500-line
cap, and are re-exported here:

- :mod:`sase.core.prompt_prediction_wire_prediction` — rows, compile
  options, requests, candidates, results, prefix-rank, and corpus stats.
- :mod:`sase.core.prompt_prediction_wire_replay` — replay options and the
  aggregate-only replay report.
- :mod:`sase.core._prompt_prediction_wire_shared` — schema version, source
  roles, and shared wire primitives.
"""

from __future__ import annotations

from sase.core._prompt_prediction_wire_shared import (
    PROMPT_PREDICTION_SOURCE_ROLES,
)
from sase.core._prompt_prediction_wire_shared import (
    PROMPT_PREDICTION_WIRE_SCHEMA_VERSION,
)
from sase.core.prompt_prediction_wire_prediction import PromptPredictionCandidate
from sase.core.prompt_prediction_wire_prediction import PromptPredictionCorpusOptions
from sase.core.prompt_prediction_wire_prediction import PromptPredictionCorpusStats
from sase.core.prompt_prediction_wire_prediction import PromptPredictionModelConfig
from sase.core.prompt_prediction_wire_prediction import PromptPredictionRequest
from sase.core.prompt_prediction_wire_prediction import PromptPredictionResult
from sase.core.prompt_prediction_wire_prediction import PromptPredictionRow
from sase.core.prompt_prediction_wire_prediction import (
    PromptPredictionWordCompletion,
)
from sase.core.prompt_prediction_wire_prediction import PromptPrefixRankMatch
from sase.core.prompt_prediction_wire_prediction import PromptPrefixRankRequest
from sase.core.prompt_prediction_wire_prediction import PromptPrefixRankResult
from sase.core.prompt_prediction_wire_prediction import (
    prompt_prediction_corpus_stats_from_dict,
)
from sase.core.prompt_prediction_wire_prediction import (
    prompt_prediction_result_from_dict,
)
from sase.core.prompt_prediction_wire_prediction import (
    prompt_prefix_rank_result_from_dict,
)
from sase.core.prompt_prediction_wire_replay import PromptPredictionReplayCohort
from sase.core.prompt_prediction_wire_replay import PromptPredictionReplayGateMetrics
from sase.core.prompt_prediction_wire_replay import (
    PromptPredictionReplayMidwordCohort,
)
from sase.core.prompt_prediction_wire_replay import (
    PromptPredictionReplayMidwordMetrics,
)
from sase.core.prompt_prediction_wire_replay import PromptPredictionReplayMidwordPreset
from sase.core.prompt_prediction_wire_replay import PromptPredictionReplayOptions
from sase.core.prompt_prediction_wire_replay import PromptPredictionReplayReport
from sase.core.prompt_prediction_wire_replay import (
    prompt_prediction_replay_report_from_dict,
)

__all__ = [
    "PROMPT_PREDICTION_WIRE_SCHEMA_VERSION",
    "PROMPT_PREDICTION_SOURCE_ROLES",
    "PromptPredictionRow",
    "PromptPredictionCorpusOptions",
    "PromptPredictionModelConfig",
    "PromptPredictionRequest",
    "PromptPredictionCandidate",
    "PromptPredictionResult",
    "PromptPrefixRankRequest",
    "PromptPrefixRankMatch",
    "PromptPrefixRankResult",
    "PromptPredictionCorpusStats",
    "PromptPredictionReplayOptions",
    "PromptPredictionReplayGateMetrics",
    "PromptPredictionReplayCohort",
    "PromptPredictionReplayReport",
    "prompt_prediction_result_from_dict",
    "prompt_prefix_rank_result_from_dict",
    "prompt_prediction_corpus_stats_from_dict",
    "prompt_prediction_replay_report_from_dict",
]
