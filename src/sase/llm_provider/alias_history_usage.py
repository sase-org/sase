"""Frontend-neutral model-usage rollup for an alias-history window.

This is the seam any surface can call after :func:`load_alias_history`: given
the shown :class:`AliasHistoryView` and an optional snapshot of the alias's
configured selector members, it returns ranked per-model counts, shares, and
pool tags. Aggregation is pure (no IO, no Textual) so it can run in the same
off-thread worker that loaded the view.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass, field

from .alias_history import AliasHistoryRun, AliasHistoryView

_UNRECORDED_LABEL = "unrecorded"


@dataclass(frozen=True, slots=True)
class AliasHistoryPoolMember:
    """One configured selector member (or a lone effective target) at H-press."""

    provider: str | None
    model: str
    effort: str | None = None
    weight: int = 1
    available: bool = True


@dataclass(frozen=True, slots=True)
class AliasHistoryModelUsage:
    """One ranked model row in an alias-history usage summary."""

    provider: str | None
    model: str | None
    effort: str | None
    effort_is_mixed: bool
    count: int
    share: float
    share_percent: int
    done: int
    failed: int
    running: int
    in_pool: bool
    is_unrecorded: bool

    @property
    def effort_label(self) -> str | None:
        """Return the rendered effort token: a concrete value, ``mixed``, or none."""
        if self.effort_is_mixed:
            return "mixed"
        return self.effort


@dataclass(frozen=True, slots=True)
class AliasHistoryUsageSummary:
    """Immutable usage rollup over the currently shown alias-history window."""

    rows: tuple[AliasHistoryModelUsage, ...]
    counted_runs: int
    duplicate_runs: int
    pool_total: int
    pool_used: int


@dataclass(slots=True)
class _UsageBucket:
    """Mutable accumulator for one ``(provider, model)`` key (or unrecorded)."""

    provider: str | None
    model: str | None
    is_unrecorded: bool
    count: int = 0
    done: int = 0
    failed: int = 0
    running: int = 0
    in_pool: bool = False
    effort_keys: set[str] = field(default_factory=set)
    effort_spellings: list[str] = field(default_factory=list)

    def add_run(self, run: AliasHistoryRun) -> None:
        self.count += 1
        if run.rollup_status == "failed":
            self.failed += 1
        elif run.rollup_status == "running":
            self.running += 1
        else:
            self.done += 1
        self._add_effort(run.reasoning_effort)

    def add_effort(self, effort: str | None) -> None:
        self._add_effort(effort)

    def _add_effort(self, effort: str | None) -> None:
        if not isinstance(effort, str):
            return
        stripped = effort.strip()
        if not stripped:
            return
        key = stripped.casefold()
        if key in self.effort_keys:
            return
        self.effort_keys.add(key)
        self.effort_spellings.append(stripped)

    @property
    def effort_fields(self) -> tuple[str | None, bool]:
        if len(self.effort_spellings) > 1:
            return None, True
        if len(self.effort_spellings) == 1:
            return self.effort_spellings[0], False
        return None, False

    @property
    def sort_label(self) -> str:
        if self.is_unrecorded:
            return _UNRECORDED_LABEL
        provider = self.provider or ""
        model = self.model or ""
        return f"{provider}/{model}".casefold()


def summarize_alias_history_usage(
    view: AliasHistoryView,
    *,
    pool: Sequence[AliasHistoryPoolMember] = (),
) -> AliasHistoryUsageSummary:
    """Rank models used by the shown window of *view*.

    Each run is keyed on ``(provider, model)`` after stripping and casefolding;
    a run with no model lands in a single ``is_unrecorded`` bucket. Counts
    never fragment on effort: a model whose runs share one effort carries that
    effort, otherwise ``effort_is_mixed`` is set.

    Pool matching: a configured member matches an observed key when both
    providers are known and both provider and model match casefolded. When
    either side's provider is unknown, match on model alone. That fallback
    keeps a bare ``sonnet`` pool member from rendering as a phantom unused
    row next to its own runs.

    Weights on pool members do not affect counts. Duplicate ``artifact_dir``
    values across groups are counted once; each skip increments
    ``duplicate_runs``.
    """
    buckets: dict[tuple[str | None, str] | None, _UsageBucket] = {}
    seen_dirs: set[str] = set()
    duplicate_runs = 0
    for group in view.groups:
        for run in group.runs:
            if run.artifact_dir in seen_dirs:
                duplicate_runs += 1
                continue
            seen_dirs.add(run.artifact_dir)
            key = _run_usage_key(run)
            bucket = buckets.get(key)
            if bucket is None:
                bucket = _bucket_for_run(run, key)
                buckets[key] = bucket
            bucket.add_run(run)

    used_member_indexes = _mark_pool_matches(buckets, pool)
    counted_runs = sum(bucket.count for bucket in buckets.values())
    counted_rows = _counted_usage_rows(buckets, counted_runs)
    unused_rows = _unused_pool_rows(pool, used_member_indexes)
    return AliasHistoryUsageSummary(
        rows=tuple(counted_rows + unused_rows),
        counted_runs=counted_runs,
        duplicate_runs=duplicate_runs,
        pool_total=len(pool),
        pool_used=len(used_member_indexes),
    )


def _run_usage_key(run: AliasHistoryRun) -> tuple[str | None, str] | None:
    model = _normalized_token(run.model)
    if model is None:
        return None
    return (_normalized_token(run.llm_provider), model.casefold())


def _normalized_token(value: str | None) -> str | None:
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    return stripped or None


def _casefold_token(value: str | None) -> str | None:
    token = _normalized_token(value)
    return token.casefold() if token is not None else None


def _bucket_for_run(
    run: AliasHistoryRun, key: tuple[str | None, str] | None
) -> _UsageBucket:
    if key is None:
        return _UsageBucket(provider=None, model=None, is_unrecorded=True)
    return _UsageBucket(
        provider=_normalized_token(run.llm_provider),
        model=_normalized_token(run.model),
        is_unrecorded=False,
    )


def _member_usage_key(member: AliasHistoryPoolMember) -> tuple[str | None, str] | None:
    model = _normalized_token(member.model)
    if model is None:
        return None
    return (_casefold_token(member.provider), model.casefold())


def _keys_match(
    member_key: tuple[str | None, str], observed_key: tuple[str | None, str]
) -> bool:
    member_provider, member_model = member_key
    observed_provider, observed_model = observed_key
    if member_model != observed_model:
        return False
    if member_provider is None or observed_provider is None:
        return True
    return member_provider == observed_provider


def _mark_pool_matches(
    buckets: dict[tuple[str | None, str] | None, _UsageBucket],
    pool: Sequence[AliasHistoryPoolMember],
) -> set[int]:
    used: set[int] = set()
    for index, member in enumerate(pool):
        member_key = _member_usage_key(member)
        if member_key is None:
            continue
        matched = False
        for observed_key, bucket in buckets.items():
            if observed_key is None or bucket.is_unrecorded:
                continue
            if _keys_match(member_key, observed_key):
                bucket.in_pool = True
                matched = True
        if matched:
            used.add(index)
    return used


def _counted_usage_rows(
    buckets: dict[tuple[str | None, str] | None, _UsageBucket],
    counted_runs: int,
) -> list[AliasHistoryModelUsage]:
    ordered = sorted(
        buckets.values(),
        key=lambda bucket: (-bucket.count, bucket.is_unrecorded, bucket.sort_label),
    )
    percents = _apportion_percents([bucket.count for bucket in ordered], counted_runs)
    rows: list[AliasHistoryModelUsage] = []
    for bucket, percent in zip(ordered, percents, strict=True):
        effort, effort_is_mixed = bucket.effort_fields
        share = (bucket.count / counted_runs) if counted_runs else 0.0
        rows.append(
            AliasHistoryModelUsage(
                provider=bucket.provider,
                model=bucket.model,
                effort=effort,
                effort_is_mixed=effort_is_mixed,
                count=bucket.count,
                share=share,
                share_percent=percent,
                done=bucket.done,
                failed=bucket.failed,
                running=bucket.running,
                in_pool=bucket.in_pool,
                is_unrecorded=bucket.is_unrecorded,
            )
        )
    return rows


def _unused_pool_rows(
    pool: Sequence[AliasHistoryPoolMember],
    used_member_indexes: set[int],
) -> list[AliasHistoryModelUsage]:
    unused: dict[tuple[str | None, str], _UsageBucket] = {}
    order: list[tuple[str | None, str]] = []
    for index, member in enumerate(pool):
        if index in used_member_indexes:
            continue
        key = _member_usage_key(member)
        if key is None:
            continue
        bucket = unused.get(key)
        if bucket is None:
            bucket = _UsageBucket(
                provider=_normalized_token(member.provider),
                model=_normalized_token(member.model),
                is_unrecorded=False,
                in_pool=True,
            )
            unused[key] = bucket
            order.append(key)
        bucket.add_effort(member.effort)
    rows: list[AliasHistoryModelUsage] = []
    for key in order:
        bucket = unused[key]
        effort, effort_is_mixed = bucket.effort_fields
        rows.append(
            AliasHistoryModelUsage(
                provider=bucket.provider,
                model=bucket.model,
                effort=effort,
                effort_is_mixed=effort_is_mixed,
                count=0,
                share=0.0,
                share_percent=0,
                done=0,
                failed=0,
                running=0,
                in_pool=True,
                is_unrecorded=False,
            )
        )
    return rows


def _apportion_percents(counts: Sequence[int], total: int) -> list[int]:
    """Largest-remainder percents so the displayed integers sum to 100 (or 0)."""
    if total <= 0 or not counts:
        return [0] * len(counts)
    exact = [count * 100 / total for count in counts]
    floors = [math.floor(value) for value in exact]
    leftover = 100 - sum(floors)
    remainders = [value - floor for value, floor in zip(exact, floors, strict=True)]
    order = sorted(range(len(counts)), key=lambda index: (-remainders[index], index))
    for index in order[:leftover]:
        floors[index] += 1
    return floors


__all__ = [
    "AliasHistoryModelUsage",
    "AliasHistoryPoolMember",
    "AliasHistoryUsageSummary",
    "summarize_alias_history_usage",
]
