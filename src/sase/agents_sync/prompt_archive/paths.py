"""Path helpers for the agents-sidecar prompt archive."""

from __future__ import annotations

from pathlib import Path, PurePosixPath
import re

_MONTH_RE = re.compile(r"^\d{6}$")


def prompts_month_dir(repo: Path | str, yyyymm: str) -> Path:
    """Return the canonical prompt directory for *yyyymm*."""

    _validate_month(yyyymm)
    return Path(repo) / "prompts" / yyyymm


def prompt_document_path(
    repo: Path | str,
    yyyymm: str,
    name: str,
) -> Path:
    """Return the canonical Markdown path for one archived prompt."""

    normalized = _safe_prompt_name(name)
    return prompts_month_dir(repo, yyyymm) / f"{normalized}.md"


def _safe_prompt_name(name: str) -> str:
    value = name.removesuffix(".md").strip()
    if not value or PurePosixPath(value).name != value or value in {".", ".."}:
        raise ValueError(f"invalid prompt archive name: {name!r}")
    return value


def _validate_month(yyyymm: str) -> None:
    if _MONTH_RE.fullmatch(yyyymm) is None:
        raise ValueError(f"invalid prompt archive month: {yyyymm!r}")


__all__ = [
    "prompt_document_path",
    "prompts_month_dir",
]
