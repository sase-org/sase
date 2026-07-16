"""Tolerance configuration for ACE PNG visual tests."""

from __future__ import annotations

import math
import os
from dataclasses import dataclass

from tests.ace.tui.visual._png_diff_comparison import (
    DEFAULT_MATERIAL_DIFF_THRESHOLD,
    PngDiffSummary,
    validate_material_diff_threshold,
)

PNG_MAX_DIFF_RATIO_ENV = "SASE_VISUAL_PNG_MAX_DIFF_RATIO"
PNG_MATERIAL_DIFF_THRESHOLD_ENV = "SASE_VISUAL_PNG_MATERIAL_DIFF_THRESHOLD"
PNG_MAX_MATERIAL_DIFF_PIXELS_ENV = "SASE_VISUAL_PNG_MAX_MATERIAL_DIFF_PIXELS"

DEFAULT_MAX_MATERIAL_DIFF_PIXELS = 0


@dataclass(frozen=True)
class PngDiffTolerance:
    """Resolved limits for an exact or tolerant PNG comparison."""

    max_diff_pixels: int | None
    max_diff_ratio: float | None
    material_diff_threshold: int
    max_material_diff_pixels: int | None
    source: str

    def is_within(self, summary: PngDiffSummary) -> bool:
        return summary.is_within(
            max_diff_pixels=self.max_diff_pixels,
            max_diff_ratio=self.max_diff_ratio,
            max_material_diff_pixels=self.max_material_diff_pixels,
        )

    def describe(self) -> str:
        pixels = (
            "no pixel cap"
            if self.max_diff_pixels is None
            else f"{self.max_diff_pixels} pixels"
        )
        ratio = (
            "no ratio cap"
            if self.max_diff_ratio is None
            else f"{self.max_diff_ratio:.6%}"
        )
        material = (
            "no material-pixel cap"
            if self.max_material_diff_pixels is None
            else f"{self.max_material_diff_pixels} material pixels"
        )
        return (
            f"{pixels}, {ratio}, and {material} above alpha-aware color "
            f"distance {self.material_diff_threshold} ({self.source})"
        )


def resolve_png_diff_tolerance(
    *,
    max_diff_pixels: int | None,
    max_diff_ratio: float | None,
    material_diff_threshold: int | None,
    max_material_diff_pixels: int | None,
) -> PngDiffTolerance:
    if any(
        value is not None
        for value in (
            max_diff_pixels,
            max_diff_ratio,
            material_diff_threshold,
            max_material_diff_pixels,
        )
    ):
        return PngDiffTolerance(
            max_diff_pixels=_validate_optional_non_negative_int(
                max_diff_pixels,
                name="max_diff_pixels",
            ),
            max_diff_ratio=_validate_optional_non_negative_float(
                max_diff_ratio,
                name="max_diff_ratio",
            ),
            material_diff_threshold=validate_material_diff_threshold(
                DEFAULT_MATERIAL_DIFF_THRESHOLD
                if material_diff_threshold is None
                else material_diff_threshold,
                name="material_diff_threshold",
            ),
            max_material_diff_pixels=_validate_optional_non_negative_int(
                DEFAULT_MAX_MATERIAL_DIFF_PIXELS
                if max_material_diff_pixels is None
                else max_material_diff_pixels,
                name="max_material_diff_pixels",
            ),
            source="explicit",
        )
    if env_tolerance := _resolve_env_png_diff_tolerance():
        return env_tolerance
    return PngDiffTolerance(
        max_diff_pixels=0,
        max_diff_ratio=0.0,
        material_diff_threshold=DEFAULT_MATERIAL_DIFF_THRESHOLD,
        max_material_diff_pixels=DEFAULT_MAX_MATERIAL_DIFF_PIXELS,
        source="default",
    )


def _resolve_env_png_diff_tolerance() -> PngDiffTolerance | None:
    raw_ratio = os.environ.get(PNG_MAX_DIFF_RATIO_ENV)
    raw_material_threshold = os.environ.get(PNG_MATERIAL_DIFF_THRESHOLD_ENV)
    raw_max_material_pixels = os.environ.get(PNG_MAX_MATERIAL_DIFF_PIXELS_ENV)
    configured = {
        name: value
        for name, value in (
            (PNG_MAX_DIFF_RATIO_ENV, raw_ratio),
            (PNG_MATERIAL_DIFF_THRESHOLD_ENV, raw_material_threshold),
            (PNG_MAX_MATERIAL_DIFF_PIXELS_ENV, raw_max_material_pixels),
        )
        if value is not None
    }
    if not configured:
        return None

    max_diff_ratio = (
        0.0
        if raw_ratio is None
        else _parse_env_non_negative_float(PNG_MAX_DIFF_RATIO_ENV, raw_ratio)
    )
    material_diff_threshold = (
        DEFAULT_MATERIAL_DIFF_THRESHOLD
        if raw_material_threshold is None
        else _parse_env_material_diff_threshold(
            PNG_MATERIAL_DIFF_THRESHOLD_ENV,
            raw_material_threshold,
        )
    )
    max_material_diff_pixels = (
        DEFAULT_MAX_MATERIAL_DIFF_PIXELS
        if raw_max_material_pixels is None
        else _parse_env_non_negative_int(
            PNG_MAX_MATERIAL_DIFF_PIXELS_ENV,
            raw_max_material_pixels,
        )
    )

    return PngDiffTolerance(
        max_diff_pixels=None,
        max_diff_ratio=max_diff_ratio,
        material_diff_threshold=material_diff_threshold,
        max_material_diff_pixels=max_material_diff_pixels,
        source=", ".join(f"${name}" for name in configured),
    )


def _parse_env_non_negative_float(name: str, raw_value: str) -> float:
    try:
        value = float(raw_value)
    except ValueError as exc:
        raise ValueError(
            f"{name} must be a finite non-negative float, got {raw_value!r}"
        ) from exc
    validated = _validate_optional_non_negative_float(value, name=name)
    assert validated is not None
    return validated


def _parse_env_non_negative_int(name: str, raw_value: str) -> int:
    try:
        value = int(raw_value)
    except ValueError as exc:
        raise ValueError(
            f"{name} must be a non-negative integer, got {raw_value!r}"
        ) from exc
    validated = _validate_optional_non_negative_int(value, name=name)
    assert validated is not None
    return validated


def _parse_env_material_diff_threshold(name: str, raw_value: str) -> int:
    value = _parse_env_non_negative_int(name, raw_value)
    return validate_material_diff_threshold(value, name=name)


def _validate_optional_non_negative_float(
    value: float | None,
    *,
    name: str,
) -> float | None:
    if value is not None and (not math.isfinite(value) or value < 0):
        raise ValueError(f"{name} must be a finite non-negative float, got {value!r}")
    return value


def _validate_optional_non_negative_int(
    value: int | None,
    *,
    name: str,
) -> int | None:
    if value is not None and (not isinstance(value, int) or value < 0):
        raise ValueError(f"{name} must be a non-negative integer, got {value!r}")
    return value
