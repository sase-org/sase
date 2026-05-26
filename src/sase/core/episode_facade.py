"""Python facade for Rust-backed episode wire helpers."""

from __future__ import annotations

from collections.abc import Sequence

from sase.core.episode_wire import (
    EpisodeSourceRefWire,
    EpisodeVerifyReportWire,
    EpisodeWire,
    episode_verify_report_from_dict,
    episode_wire_to_json_dict,
)
from sase.core.rust import require_rust_binding


def episode_wire_schema_version() -> int:
    rust_schema_version = require_rust_binding("episode_wire_schema_version")
    return int(rust_schema_version())


def canonical_episode_json(episode: EpisodeWire) -> str:
    rust_canonical_json = require_rust_binding("canonical_episode_json")
    return str(rust_canonical_json(episode_wire_to_json_dict(episode)))


def generate_source_id(source: EpisodeSourceRefWire) -> str:
    rust_source_id = require_rust_binding("episode_source_id")
    return str(rust_source_id(episode_wire_to_json_dict(source)))


def generate_episode_id(
    project: str,
    root_source_id: str,
    sources: Sequence[EpisodeSourceRefWire],
) -> str:
    rust_episode_id = require_rust_binding("episode_id")
    return str(
        rust_episode_id(
            project,
            root_source_id,
            episode_wire_to_json_dict(list(sources)),
        )
    )


def verify_episode_sources(
    episode_id: str,
    sources: Sequence[EpisodeSourceRefWire],
) -> EpisodeVerifyReportWire:
    rust_verify_sources = require_rust_binding("verify_episode_sources")
    payload = rust_verify_sources(
        episode_id,
        episode_wire_to_json_dict(list(sources)),
    )
    return episode_verify_report_from_dict(payload)


__all__ = [
    "canonical_episode_json",
    "episode_wire_schema_version",
    "generate_episode_id",
    "generate_source_id",
    "verify_episode_sources",
]
