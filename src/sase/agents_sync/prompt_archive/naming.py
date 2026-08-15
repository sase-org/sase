"""Deterministic naming for canonical archived prompts."""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path, PurePosixPath


def resolve_prompt_name(
    plan_slug: str | None,
    sase_agent: str,
    existing_listing: Iterable[str | Path],
    *,
    reusable_names: Iterable[str] = (),
) -> str:
    """Resolve a stable name, suffixing collisions with another run.

    ``reusable_names`` identifies existing documents already owned by this
    run, which lets repeated commits update one prompt byte-for-byte.
    """

    base = _safe_name(plan_slug or sase_agent)
    existing = {Path(value).name.removesuffix(".md") for value in existing_listing}
    reusable = {value.removesuffix(".md") for value in reusable_names}
    if base not in existing or base in reusable:
        return base
    suffix = 1
    while True:
        candidate = f"{base}_{suffix}"
        if candidate not in existing or candidate in reusable:
            return candidate
        suffix += 1


def _safe_name(value: str) -> str:
    normalized = value.removesuffix(".md").strip()
    if (
        not normalized
        or PurePosixPath(normalized).name != normalized
        or normalized in {".", ".."}
    ):
        raise ValueError(f"invalid prompt archive name: {value!r}")
    return normalized


__all__ = ["resolve_prompt_name"]
