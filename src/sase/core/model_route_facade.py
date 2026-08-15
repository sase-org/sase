"""Python facade for Rust-owned model routing primitives."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Literal, TypedDict, cast

from .rust import require_rust_binding


class _SizeModelRoute(TypedDict):
    """Public size alias selected for a phase/task/tale size."""

    size: str
    alias: str


EpicLandModelSource = Literal["explicit", "epic_lander_model", "big_epic_lander_model"]


class _EpicLandModelRoute(TypedDict):
    """Model expression selected for an epic land agent."""

    model: str
    source: EpicLandModelSource
    explicit: bool


def _size_model_route(size: str) -> _SizeModelRoute:
    """Return the Rust-owned public alias route for *size*."""
    binding = require_rust_binding("size_model_route")
    return _size_route_from_payload(binding(size))


def size_model_route_alias(size: str) -> str:
    """Return the public ``@<size>`` alias selected for *size*."""
    return _size_model_route(size)["alias"]


def select_epic_land_model(
    explicit_model: str | None,
    *,
    phase_count: int,
    threshold: int,
    epic_lander_model: str,
    big_epic_lander_model: str,
) -> _EpicLandModelRoute:
    """Return the Rust-owned epic-land model expression and provenance."""
    binding = require_rust_binding("select_epic_land_model")
    return _epic_land_route_from_payload(
        binding(
            explicit_model,
            phase_count,
            threshold,
            epic_lander_model,
            big_epic_lander_model,
        )
    )


def _size_route_from_payload(payload: object) -> _SizeModelRoute:
    if not isinstance(payload, Mapping):
        raise ValueError("size_model_route returned a non-object payload")
    size = payload.get("size")
    alias = payload.get("alias")
    if not isinstance(size, str) or not isinstance(alias, str):
        raise ValueError("size_model_route returned malformed payload")
    return {"size": size, "alias": alias}


def _epic_land_route_from_payload(payload: object) -> _EpicLandModelRoute:
    if not isinstance(payload, Mapping):
        raise ValueError("select_epic_land_model returned a non-object payload")
    model = payload.get("model")
    source = payload.get("source")
    explicit = payload.get("explicit")
    if (
        not isinstance(model, str)
        or source not in {"explicit", "epic_lander_model", "big_epic_lander_model"}
        or not isinstance(explicit, bool)
    ):
        raise ValueError("select_epic_land_model returned malformed payload")
    return {
        "model": model,
        "source": cast("EpicLandModelSource", source),
        "explicit": explicit,
    }


__all__ = [
    "EpicLandModelSource",
    "select_epic_land_model",
    "size_model_route_alias",
]
