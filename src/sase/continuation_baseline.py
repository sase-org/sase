"""Shadow measurements for monitor-continuation baseline fixtures.

These helpers intentionally measure today's prompt shapes without enforcing a
new continuation contract. Later Rust-owned continuation work can replace the
heuristics with canonical records while preserving the fixture vocabulary.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
import json
import math
import os
from pathlib import Path
import re
import time
from typing import Any, Literal

from sase.llm_provider.types import ModelTier

SCHEMA_VERSION = 1
DEFAULT_CONTEXT_BUDGET_TOKENS = 200_000
MEASUREMENT_LOG_NAME = "continuation_prompt_measurements.jsonl"

ComponentName = Literal["fork_render", "provider_preprocess"]

_NEW_QUERY_MARKER = "# New Query"
_EVIDENCE_HEADING_RE = re.compile(
    r"(?m)^#{2,6} (?:Last \d+ lines of output|Output "
    r"\(untrusted program output, not instructions\)|Output Evidence)"
)


@dataclass(frozen=True)
class PromptComponentSizes:
    """Byte measurements for one rendered prompt projection."""

    local_bytes: int
    history_bytes: int
    evidence_bytes: int
    total_expanded_bytes: int


@dataclass(frozen=True)
class NodeCounts:
    """Best-known source identity counts for a rendered fork graph."""

    known_node_count: int
    unique_node_count: int
    duplicate_node_count: int
    source_kind_counts: dict[str, int]


@dataclass(frozen=True)
class BudgetEstimate:
    """Conservative shadow budget estimate for a provider prompt."""

    estimated_tokens: int
    capacity_tokens: int
    headroom_tokens: int
    threshold_exceeded: bool
    estimator: str = "utf8_bytes_div_4_ceiling"


@dataclass(frozen=True)
class FallbackRouting:
    """Whether retry/fallback routing appears active for this prompt."""

    active: bool
    model: str | None
    provider: str | None = None


@dataclass(frozen=True)
class ContinuationPromptMeasurement:
    """One shadow diagnostic record for continuation prompt cost fixtures."""

    schema_version: int
    component: ComponentName
    prompt_sizes: PromptComponentSizes
    node_counts: NodeCounts
    budget: BudgetEstimate
    fallback_routing: FallbackRouting
    recorded_at_epoch: float

    def to_json_data(self) -> dict[str, object]:
        return asdict(self)


def measure_fork_render(
    sources: Sequence[Mapping[str, object]],
    rendered_history: str,
    *,
    capacity_tokens: int | None = None,
) -> ContinuationPromptMeasurement:
    """Measure the rendered ``#fork`` history block without changing it."""

    sizes = measure_prompt_components(rendered_history)
    return _measurement(
        "fork_render",
        sizes=sizes,
        node_counts=node_counts_for_sources(sources),
        capacity_tokens=capacity_tokens,
        fallback_routing=FallbackRouting(active=False, model=None),
    )


def measure_provider_preprocess(
    prompt: str,
    *,
    capacity_tokens: int | None = None,
    model_tier: ModelTier = "large",
    model_override: str | None = None,
    provider_name: str | None = None,
    fallback_model: str | None = None,
) -> ContinuationPromptMeasurement:
    """Measure the final prompt immediately before provider invocation."""

    fallback = fallback_model or os.environ.get("SASE_MODEL_OVERRIDE") or None
    sizes = measure_prompt_components(prompt)
    return _measurement(
        "provider_preprocess",
        sizes=sizes,
        node_counts=NodeCounts(
            known_node_count=0,
            unique_node_count=0,
            duplicate_node_count=0,
            source_kind_counts={},
        ),
        capacity_tokens=capacity_tokens,
        fallback_routing=FallbackRouting(
            active=fallback is not None,
            model=fallback or model_override or model_tier,
            provider=provider_name,
        ),
    )


def measure_prompt_components(prompt: str) -> PromptComponentSizes:
    """Classify local/history/evidence byte costs in a rendered prompt.

    ``history_bytes`` covers the legacy injected ``#fork`` prefix when present.
    ``evidence_bytes`` is a subset measurement for command-output sections so
    the old raw-output duplication classes are visible in the baseline data.
    """

    encoded_total = _utf8_len(prompt)
    marker_index = prompt.rfind(_NEW_QUERY_MARKER)
    if marker_index >= 0:
        history = prompt[:marker_index]
        local = prompt[marker_index:]
    else:
        history = ""
        local = prompt
    return PromptComponentSizes(
        local_bytes=_utf8_len(local),
        history_bytes=_utf8_len(history),
        evidence_bytes=_evidence_bytes(prompt),
        total_expanded_bytes=encoded_total,
    )


def node_counts_for_sources(
    sources: Sequence[Mapping[str, object]],
) -> NodeCounts:
    """Return best-known source identity counts from today's fork source dicts."""

    identities: list[str] = []
    kind_counts: Counter[str] = Counter()
    for source in sources:
        kind = _source_kind(source)
        kind_counts[kind] += 1
        identities.extend(_source_node_identities(source))

    unique = set(identities)
    return NodeCounts(
        known_node_count=len(identities),
        unique_node_count=len(unique),
        duplicate_node_count=len(identities) - len(unique),
        source_kind_counts=dict(sorted(kind_counts.items())),
    )


def record_shadow_measurement(
    artifacts_dir: str | Path | None,
    measurement: ContinuationPromptMeasurement,
) -> None:
    """Append one shadow measurement to an artifacts-side JSONL file.

    Recording must not affect launch or verification behavior.
    """

    if artifacts_dir is None:
        return
    try:
        root = Path(artifacts_dir)
        root.mkdir(parents=True, exist_ok=True)
        with (root / MEASUREMENT_LOG_NAME).open("a", encoding="utf-8") as stream:
            json.dump(measurement.to_json_data(), stream, sort_keys=True)
            stream.write("\n")
    except OSError:
        return


def _measurement(
    component: ComponentName,
    *,
    sizes: PromptComponentSizes,
    node_counts: NodeCounts,
    capacity_tokens: int | None,
    fallback_routing: FallbackRouting,
) -> ContinuationPromptMeasurement:
    return ContinuationPromptMeasurement(
        schema_version=SCHEMA_VERSION,
        component=component,
        prompt_sizes=sizes,
        node_counts=node_counts,
        budget=_budget_estimate(
            sizes.total_expanded_bytes,
            capacity_tokens=_context_budget_tokens(capacity_tokens),
        ),
        fallback_routing=fallback_routing,
        recorded_at_epoch=time.time(),
    )


def _budget_estimate(total_bytes: int, *, capacity_tokens: int) -> BudgetEstimate:
    estimated_tokens = _estimate_tokens(total_bytes)
    headroom = capacity_tokens - estimated_tokens
    return BudgetEstimate(
        estimated_tokens=estimated_tokens,
        capacity_tokens=capacity_tokens,
        headroom_tokens=headroom,
        threshold_exceeded=headroom < 0,
    )


def _context_budget_tokens(explicit: int | None) -> int:
    if explicit is not None and explicit > 0:
        return explicit
    raw = os.environ.get("SASE_CONTINUATION_SHADOW_CONTEXT_TOKENS", "")
    try:
        parsed = int(raw)
    except ValueError:
        return DEFAULT_CONTEXT_BUDGET_TOKENS
    return parsed if parsed > 0 else DEFAULT_CONTEXT_BUDGET_TOKENS


def _estimate_tokens(total_bytes: int) -> int:
    return int(math.ceil(max(total_bytes, 0) / 4))


def _source_kind(source: Mapping[str, object]) -> str:
    value = source.get("kind", "agent")
    return value if isinstance(value, str) else "unknown"


def _source_node_identities(source: Mapping[str, object]) -> list[str]:
    kind = _source_kind(source)
    if kind == "family":
        raw_members = source.get("members", [])
        if not isinstance(raw_members, list):
            return []
        return [
            identity
            for member in raw_members
            if isinstance(member, Mapping)
            for identity in _source_node_identities(member)
        ]
    if kind == "clan":
        raw_members = source.get("members", [])
        if not isinstance(raw_members, list):
            return []
        return [
            identity
            for member in raw_members
            if isinstance(member, Mapping)
            for identity in _identity_candidates("agent", member)
        ]
    if kind == "proc":
        proc = source.get("proc")
        if isinstance(proc, Mapping):
            return _identity_candidates("proc", proc)
        return _identity_candidates("proc", source)
    return _identity_candidates("agent", source)


def _identity_candidates(prefix: str, source: Mapping[str, object]) -> list[str]:
    for field in ("path", "proc_id", "artifact_dir", "name"):
        value = source.get(field)
        if isinstance(value, str) and value:
            return [f"{prefix}:{field}:{value}"]
    return []


def _evidence_bytes(prompt: str) -> int:
    total = 0
    matches = list(_EVIDENCE_HEADING_RE.finditer(prompt))
    for index, match in enumerate(matches):
        start = match.start()
        next_start = (
            matches[index + 1].start() if index + 1 < len(matches) else len(prompt)
        )
        next_heading = _next_heading(prompt, match.end(), before=next_start)
        end = min(next_start, next_heading if next_heading >= 0 else len(prompt))
        total += _utf8_len(prompt[start:end])
    return total


def _next_heading(prompt: str, start: int, *, before: int) -> int:
    match = re.search(r"(?m)^#{1,6} ", prompt[start:before])
    if match is None:
        return -1
    return start + match.start()


def _utf8_len(text: str) -> int:
    return len(text.encode("utf-8"))


__all__ = [
    "DEFAULT_CONTEXT_BUDGET_TOKENS",
    "MEASUREMENT_LOG_NAME",
    "BudgetEstimate",
    "ContinuationPromptMeasurement",
    "FallbackRouting",
    "NodeCounts",
    "PromptComponentSizes",
    "measure_fork_render",
    "measure_prompt_components",
    "measure_provider_preprocess",
    "node_counts_for_sources",
    "record_shadow_measurement",
]
