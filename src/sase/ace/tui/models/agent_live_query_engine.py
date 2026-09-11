"""Rust-backed committed-query engine for the live Agents tab (sase-zf.2).

Behind the ``agents_unified_query`` sunset flag, the Agents tab parses and
evaluates its committed filter through the ``agents-live``
:class:`~sase.ace.query_profile.compiler.CompiledQueryProfile` and the same
Rust ``compile_query_with_profile`` / ``evaluate_many`` bindings the
Artifacts panes use (:mod:`sase.core.query_profile_corpus_facade`), instead
of the legacy :mod:`sase.ace.agent_query` parser/evaluator.

:func:`build_agents_live_query_index` compiles the Rust corpus for one
agents snapshot. Full/delta reloads and the content-index refresh worker
build it off the Textual event loop (``actions/agents/_loading_compute_finalize.py``
and ``actions/agents/_loading_filter.py``); the in-memory sync refilter path
(``actions/agents/_loading_finalize.py``) prefers a cached
:class:`AgentsLiveQueryFacade` from one of those workers but falls back to
building inline on a cache miss. This phase's query editing is
commit-only — the modal validates on Apply/Enter, not per keystroke — so an
inline rebuild there fires at committed-query-change/list-mutation
frequency, the same order of work as the legacy per-row Python loop it
replaces, not a per-keystroke hot path. A future live-typing preview
(filter-bar-ui phase) must route every build off-thread before it can rely
on per-keystroke evaluation.

The resulting :class:`AgentsLiveQueryFacade` is deliberately keyed on
``(canonical_query, profile_digest)`` only, not a snapshot generation:
applying a facade computed against a slightly stale agent snapshot to a
freshly mutated list is bounded, self-healing staleness (a brand-new agent
may be briefly excluded until the next off-thread rebuild lands) — the same
trade-off :class:`~sase.ace.tui.models.agent_content_search.AgentContentSearchIndex`
already accepts elsewhere in this pipeline.
"""

from __future__ import annotations

from collections.abc import Collection, Iterable
from dataclasses import dataclass
import re
from typing import TYPE_CHECKING

from sase.ace.query.profile_reference import canonical_query_for_profile
from sase.ace.query.profile_reference_support import ProfileQueryError
from sase.ace.query.types import PropertyMatch, to_canonical_string
from sase.ace.query_profile import (
    CompiledQueryProfile,
    compiled_profile_for_builtin_pane,
)
from sase.core.agent_types import AgentIdentity
from sase.core.query_profile_corpus_facade import (
    ArtifactQueryIndex,
    compile_artifact_query_index,
    evaluate_artifact_query_many,
)
from sase.feature_flags import FeatureFlag, current_flags

from .agent_live_query import agent_live_query_entry, agent_live_query_row_id

if TYPE_CHECKING:
    from .agent import Agent
    from .agent_content_search import AgentContentSearchIndex

AGENTS_LIVE_PANE_ID = "agents-live"


def agents_unified_query_enabled() -> bool:
    """Return whether the Agents tab should use the unified query engine."""
    return current_flags().enabled(FeatureFlag.agents_unified_query)


def agents_live_query_profile() -> CompiledQueryProfile:
    """Return the compiled ``agents-live`` query profile."""
    profile = compiled_profile_for_builtin_pane(AGENTS_LIVE_PANE_ID)
    assert profile is not None
    return profile


def build_agents_live_query_index(
    agents: Iterable[Agent],
    *,
    generation: int,
    content_index: AgentContentSearchIndex | None = None,
    unread_agent_ids: Collection[AgentIdentity] = (),
    profile: CompiledQueryProfile | None = None,
) -> ArtifactQueryIndex:
    """Build the off-thread Rust corpus for one Agents-tab snapshot.

    Callers must run this off the Textual event loop: row projection and
    Rust corpus compilation are both real work proportional to agent count.
    """
    compiled_profile = profile if profile is not None else agents_live_query_profile()
    return compile_artifact_query_index(
        pane_id=AGENTS_LIVE_PANE_ID,
        generation=generation,
        profile=compiled_profile,
        entries=(
            agent_live_query_entry(
                agent,
                content_cache=content_index,
                unread_agent_ids=unread_agent_ids,
            )
            for agent in agents
        ),
    )


@dataclass(frozen=True, slots=True)
class AgentsLiveQueryFacade:
    """One committed agents-live query's matched-row-id set."""

    canonical_query: str
    profile_digest: str
    source_row_ids: frozenset[str]
    matched_row_ids: frozenset[str]

    def matches(self, agent: Agent) -> bool:
        return agent_live_query_row_id(agent) in self.matched_row_ids

    def covers(self, agents: Iterable[Agent]) -> bool:
        """Return whether this mask was evaluated against every given row."""
        return all(
            agent_live_query_row_id(agent) in self.source_row_ids for agent in agents
        )

    def is_current_for(
        self, canonical_query: str, profile: CompiledQueryProfile
    ) -> bool:
        return (
            self.canonical_query == canonical_query
            and self.profile_digest == profile.digest
        )


_AGE_HINT_RE = re.compile(r"\bage\s*(<=|>=|<|>|:)\s*(\d+[smhd])\b", re.IGNORECASE)
_TYPE_HINT_RE = re.compile(r'\btype\s*:\s*"?(workflow|run|running)"?', re.IGNORECASE)


def _legacy_token_hint(raw_query: str) -> str | None:
    """Return a ``try <unified-term>`` hint when *raw_query* names a retired token.

    Mirrors the legacy -> unified mapping table in the epic plan
    (``sase/repos/plans/202609/agents_query_unification.md``). ``age`` maps by
    comparison direction (``>``/``>=``/``:`` sugar -> ``until:``, ``<``/``<=``
    -> ``since:``); ``=`` has no clean single-field equivalent and is left
    unhinted.
    """
    match = _AGE_HINT_RE.search(raw_query)
    if match is not None:
        op, duration = match.group(1), match.group(2).lower()
        if op in (">", ">=", ":"):
            return f"try until:{duration}"
        if op in ("<", "<="):
            return f"try since:{duration}"
    match = _TYPE_HINT_RE.search(raw_query)
    if match is not None:
        target = "workflow" if match.group(1).lower() == "workflow" else "agent"
        return f"try kind:{target}"
    return None


def augment_error_with_legacy_hint(message: str, raw_query: str) -> str:
    """Append a legacy-token replacement hint to a parse-error message."""
    hint = _legacy_token_hint(raw_query)
    return f"{message} — {hint}" if hint else message


def evaluate_agents_live_query(
    query: str,
    index: ArtifactQueryIndex,
) -> tuple[AgentsLiveQueryFacade | None, str | None]:
    """Evaluate *query* against *index*.

    Returns ``(facade, None)`` on success or ``(None, error_message)`` on a
    parse failure — exactly one of the two is not ``None``. The error
    message is enriched with the legacy-token hint when applicable.
    """
    try:
        canonical = canonical_query_for_profile(query, index.profile)
        result = evaluate_artifact_query_many(query, index, canonical_query=canonical)
    except ProfileQueryError as exc:
        return None, augment_error_with_legacy_hint(str(exc), query)
    facade = AgentsLiveQueryFacade(
        canonical_query=result.cache_key.canonical_query,
        profile_digest=index.profile.digest,
        source_row_ids=frozenset(index.row_ids),
        matched_row_ids=frozenset(result.matched_row_ids),
    )
    return facade, None


def agents_live_property_query_term(key: str, value: str) -> str:
    """Build and validate one ``key:value`` term through the live profile."""
    raw = to_canonical_string(PropertyMatch(key=key, value=value))
    return canonical_query_for_profile(raw, agents_live_query_profile())


def apply_agents_live_query_filter(
    query: str,
    agents: Iterable[Agent],
    *,
    content_index: AgentContentSearchIndex | None = None,
    unread_agent_ids: Collection[AgentIdentity] = (),
    cached_facade: AgentsLiveQueryFacade | None = None,
    generation: int = 0,
    profile: CompiledQueryProfile | None = None,
) -> tuple[list[Agent], AgentsLiveQueryFacade | None, str | None]:
    """Filter *agents* through the committed live-query mask facade."""
    materialized = list(agents)
    raw = (query or "").strip()
    if not raw:
        return materialized, None, None

    compiled_profile = profile if profile is not None else agents_live_query_profile()
    try:
        canonical = canonical_query_for_profile(raw, compiled_profile)
    except ProfileQueryError as exc:
        return (
            materialized,
            None,
            augment_error_with_legacy_hint(str(exc), raw),
        )

    facade = cached_facade
    if (
        facade is None
        or not facade.is_current_for(canonical, compiled_profile)
        or not facade.covers(materialized)
    ):
        index = build_agents_live_query_index(
            materialized,
            generation=generation,
            content_index=content_index,
            unread_agent_ids=unread_agent_ids,
            profile=compiled_profile,
        )
        facade, error = evaluate_agents_live_query(raw, index)
        if facade is None:
            return materialized, None, error

    from ._agent_tree import filter_tree_rows

    return filter_tree_rows(materialized, facade.matches), facade, None


__all__ = [
    "AGENTS_LIVE_PANE_ID",
    "AgentsLiveQueryFacade",
    "agents_live_property_query_term",
    "agents_live_query_profile",
    "agents_unified_query_enabled",
    "apply_agents_live_query_filter",
    "augment_error_with_legacy_hint",
    "build_agents_live_query_index",
    "evaluate_agents_live_query",
]
