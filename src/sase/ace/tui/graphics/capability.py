"""Terminal color context for ACE image previews."""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass


@dataclass(frozen=True)
class ImageRenderContext:
    """Small rendering context for Pillow-backed image previews."""

    truecolor: bool
    reason: str = "terminal color support inferred from environment"


def has_truecolor(env: Mapping[str, str] | None = None) -> bool:
    """Return whether the environment advertises 24-bit color support."""
    env = os.environ if env is None else env
    colorterm = env.get("COLORTERM", "").lower()
    term = env.get("TERM", "").lower()
    return colorterm in {"truecolor", "24bit"} or "truecolor" in term


def image_render_context(env: Mapping[str, str] | None = None) -> ImageRenderContext:
    """Build the side-effect-free image preview rendering context."""
    truecolor = has_truecolor(env)
    reason = (
        "truecolor advertised by terminal environment"
        if truecolor
        else "terminal truecolor support was not advertised"
    )
    return ImageRenderContext(truecolor=truecolor, reason=reason)
