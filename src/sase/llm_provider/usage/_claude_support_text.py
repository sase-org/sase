"""Text normalization helpers shared across Claude usage support modules."""

from __future__ import annotations

import re
import unicodedata


def normalize_text(text: str) -> str:
    """Normalize Claude CLI text output for stable parsing and comparison."""
    normalized = unicodedata.normalize("NFKC", str(text))
    return re.sub(r"\s+", " ", normalized).strip()


def slugify(text: str) -> str:
    """Slugify Claude usage-window label text into a stable identifier."""
    normalized = normalize_text(text).casefold()
    slug = re.sub(r"[^a-z0-9]+", "-", normalized).strip("-")
    return slug or "unknown"


def label_words(text: str) -> str:
    """Return a Claude usage-window label as space-separated slug words."""
    slug = slugify(text)
    return slug.replace("-", " ")
