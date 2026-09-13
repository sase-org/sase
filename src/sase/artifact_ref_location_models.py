"""Line-location models for pager link targets."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, cast

from sase.artifact_ref_wire import optional_int


@dataclass(frozen=True, slots=True)
class LinkLocation:
    """One optional line/column/range target on a link."""

    line: int
    column: int | None = None
    end_line: int | None = None

    @classmethod
    def from_wire(cls, raw: Mapping[str, Any]) -> LinkLocation:
        return cls(
            line=int(raw["line"]),
            column=optional_int(raw.get("column")),
            end_line=optional_int(raw.get("end_line")),
        )


@dataclass(frozen=True, slots=True)
class LinkLocationSplit:
    """A target string split into its base ref and optional location."""

    base: str
    location: LinkLocation | None = None

    @classmethod
    def from_wire(cls, raw: Mapping[str, Any]) -> LinkLocationSplit:
        raw_location = raw.get("location")
        return cls(
            base=str(raw["base"]),
            location=(
                None
                if raw_location is None
                else LinkLocation.from_wire(cast(Mapping[str, Any], raw_location))
            ),
        )


__all__ = ["LinkLocation", "LinkLocationSplit"]
