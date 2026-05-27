"""Verification helpers for deterministic episodic-memory episodes."""

from __future__ import annotations

from collections.abc import Sequence

from sase.core.episode_facade import verify_episode_sources
from sase.core.episode_wire import (
    EpisodeSourceRefWire,
    EpisodeVerifyReportWire,
    EpisodeWire,
)


def verify_episode(episode: EpisodeWire) -> EpisodeVerifyReportWire:
    """Recompute source state for an episode without mutating it."""

    return verify_episode_source_refs(episode.episode_id, episode.sources)


def verify_episode_source_refs(
    episode_id: str,
    sources: Sequence[EpisodeSourceRefWire],
) -> EpisodeVerifyReportWire:
    """Verify source refs through the Rust-backed canonical helper."""

    return verify_episode_sources(episode_id, sources)


__all__ = [
    "verify_episode",
    "verify_episode_source_refs",
]
