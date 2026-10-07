"""Section models, constants, and wire helpers for bundle assembly."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from typing import Any

#: Frame title when neither the project nor the home root resolves one.
DEFAULT_FRAME_TITLE = "SASE Agent Instructions"

#: Relative path of the generated contract note treated as superseded input.
GENERATED_CONTRACT_RELATIVE_PATH = "sase/memory/sase.md"

#: Stable manifest source path for the packaged contract template.
PACKAGED_TEMPLATE_SOURCE_PATH = (
    "sase/main/init_memory/templates/memory-sase.template.md"
)

#: Stable manifest source path for the packaged helper template.
HELPER_TEMPLATE_SOURCE_PATH = (
    "sase/llm_provider/templates/claude_helper_instructions.md"
)

_INVALID_SLUG_RE = re.compile(r"[^a-z0-9_-]+")


@dataclass
class SectionBuilder:
    """Mutable section accumulator; excluded sections carry no bytes."""

    id: str
    layer: str
    lifecycle: str = "neutral"
    required: bool = False
    provider_specific: bool = False
    text: str | None = None
    reason: str | None = None
    shadowed_by: str | None = None
    sources: list[dict[str, Any]] = field(default_factory=list)


def section_slug(text: str) -> str:
    """Return the section-id slug for a note stem or template heading."""
    slug = _INVALID_SLUG_RE.sub("_", text.strip().lower()).strip("_")
    slug = re.sub(r"_+", "_", slug)
    return slug or "section"


def tokens_estimate(text: str) -> int:
    """Return the ``tokens_est`` estimate (``ceil(len/4)``) for *text*."""
    return -(-len(text) // 4)


def section_wire_dict(section: SectionBuilder, *, offset: int | None) -> dict[str, Any]:
    """Return the wire-shaped section dict for one built section."""
    if section.text is not None:
        data = section.text.encode("utf-8")
        wire: dict[str, Any] = {
            "id": section.id,
            "layer": section.layer,
            "status": "included",
            "lifecycle": section.lifecycle,
            "required": section.required,
            "provider_specific": section.provider_specific,
            "offset": offset,
            "length": len(data),
            "sha256": hashlib.sha256(data).hexdigest(),
            "tokens_est": tokens_estimate(section.text),
            "sources": section.sources,
        }
        return wire
    return {
        "id": section.id,
        "layer": section.layer,
        "status": "excluded",
        "lifecycle": section.lifecycle,
        "required": section.required,
        "provider_specific": section.provider_specific,
        "tokens_est": 0,
        "sources": section.sources,
        "reason": section.reason,
        **({"shadowed_by": section.shadowed_by} if section.shadowed_by else {}),
    }


__all__ = [
    "DEFAULT_FRAME_TITLE",
    "GENERATED_CONTRACT_RELATIVE_PATH",
    "HELPER_TEMPLATE_SOURCE_PATH",
    "PACKAGED_TEMPLATE_SOURCE_PATH",
    "SectionBuilder",
    "section_slug",
    "section_wire_dict",
    "tokens_estimate",
]
