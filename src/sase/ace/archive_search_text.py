"""Search-text projection helpers for dismissed agent archives."""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .tui.models.agent import Agent

ARCHIVE_BUNDLE_SCHEMA_VERSION = 2
ARCHIVE_REVISION = 1
ARCHIVE_SEARCH_SCRUBBER_VERSION = 1

MAX_ARCHIVE_SEARCH_TEXT_CHARS = 128 * 1024
MAX_ARCHIVE_SOURCE_CHARS = 32 * 1024

_TOKEN_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\b(sk-[A-Za-z0-9_-]{16,})\b"),
    re.compile(r"\b(sk-ant-[A-Za-z0-9_-]{16,})\b"),
    re.compile(r"\b(gh[opsu]_[A-Za-z0-9_]{20,})\b"),
    re.compile(r"\b(AIza[0-9A-Za-z_-]{20,})\b"),
    re.compile(r"\b(AKIA[0-9A-Z]{16})\b"),
)
_ASSIGNMENT_PATTERN = re.compile(
    r"(?i)\b((?:api[_-]?key|access[_-]?token|auth[_-]?token|secret|password)"
    r"\s*[:=]\s*)([^\s'\"`]+)"
)
_BEARER_PATTERN = re.compile(r"(?i)\b(Bearer\s+)([A-Za-z0-9._~+/=-]{16,})")


def build_archive_search_text(agent: Agent) -> str:
    """Build the bounded, scrubbed text projection for *agent*."""

    paths = _paths_for_agent(agent)
    parts = [_read_text(path) for path in paths]
    for attempt in getattr(agent, "attempt_history", ()):
        live_reply_path = getattr(attempt, "live_reply_path", None)
        if live_reply_path:
            parts.append(_read_text(Path(os.path.expanduser(live_reply_path))))
    return _scrub_archive_search_text("\n\n".join(part for part in parts if part))


def normalize_archive_bundle_projection(bundle: dict[str, Any]) -> bool:
    """Ensure archive schema metadata and search text exist in *bundle*.

    Returns ``True`` when the bundle dict was changed.
    """

    changed = False
    bundle_schema_version = _int_or_none(bundle.get("bundle_schema_version"))
    if (
        bundle_schema_version is None
        or bundle_schema_version < ARCHIVE_BUNDLE_SCHEMA_VERSION
    ):
        bundle["bundle_schema_version"] = ARCHIVE_BUNDLE_SCHEMA_VERSION
        changed = True
    archive_revision = _int_or_none(bundle.get("archive_revision"))
    if archive_revision is None or archive_revision < ARCHIVE_REVISION:
        bundle["archive_revision"] = ARCHIVE_REVISION
        changed = True
    scrubber_version = _int_or_none(bundle.get("archive_search_scrubber_version"))
    if scrubber_version is None or scrubber_version < ARCHIVE_SEARCH_SCRUBBER_VERSION:
        bundle["archive_search_scrubber_version"] = ARCHIVE_SEARCH_SCRUBBER_VERSION
        changed = True

    existing = bundle.get("archive_search_text")
    if isinstance(existing, str) and existing:
        scrubbed = _scrub_archive_search_text(existing)
        if scrubbed != existing:
            bundle["archive_search_text"] = scrubbed
            changed = True
        return changed

    projection = _build_archive_search_text_from_bundle(bundle)
    if projection:
        bundle["archive_search_text"] = projection
        changed = True
    return changed


def _build_archive_search_text_from_bundle(bundle: dict[str, Any]) -> str:
    """Build search text from bundle paths for legacy backfills."""

    paths = _paths_for_bundle(bundle)
    parts = [_read_text(path) for path in paths]
    return _scrub_archive_search_text("\n\n".join(part for part in parts if part))


def _scrub_archive_search_text(text: str) -> str:
    """Redact obvious high-risk secret patterns from archive search text."""

    scrubbed = _ASSIGNMENT_PATTERN.sub(r"\1[REDACTED]", text)
    scrubbed = _BEARER_PATTERN.sub(r"\1[REDACTED]", scrubbed)
    for pattern in _TOKEN_PATTERNS:
        scrubbed = pattern.sub("[REDACTED]", scrubbed)
    return scrubbed[:MAX_ARCHIVE_SEARCH_TEXT_CHARS]


def _paths_for_agent(agent: Agent) -> list[Path]:
    paths: list[Path] = []
    artifacts_dir = agent.get_artifacts_dir()
    if artifacts_dir:
        artifacts = Path(artifacts_dir)
        paths.append(artifacts / "raw_xprompt.md")
        paths.append(artifacts / "live_reply.md")
        paths.extend(_chat_paths_from_meta(artifacts / "agent_meta.json"))
    response_path = getattr(agent, "response_path", None)
    if response_path:
        paths.append(Path(os.path.expanduser(response_path)))
    return _dedupe_paths(paths)


def _paths_for_bundle(bundle: dict[str, Any]) -> list[Path]:
    paths: list[Path] = []
    artifacts_dir = bundle.get("artifacts_dir")
    if isinstance(artifacts_dir, str) and artifacts_dir:
        artifacts = Path(os.path.expanduser(artifacts_dir))
        paths.append(artifacts / "raw_xprompt.md")
        paths.append(artifacts / "live_reply.md")
        paths.extend(_chat_paths_from_meta(artifacts / "agent_meta.json"))
    response_path = bundle.get("response_path")
    if isinstance(response_path, str) and response_path:
        paths.append(Path(os.path.expanduser(response_path)))
    return _dedupe_paths(paths)


def _chat_paths_from_meta(meta_path: Path) -> list[Path]:
    try:
        data = json.loads(meta_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    if not isinstance(data, dict):
        return []
    chat_path = data.get("chat_path")
    if not isinstance(chat_path, str) or not chat_path:
        return []
    return [Path(os.path.expanduser(chat_path))]


def _read_text(path: Path) -> str:
    try:
        with path.open(encoding="utf-8", errors="replace") as f:
            return f.read(MAX_ARCHIVE_SOURCE_CHARS)
    except OSError:
        return ""


def _dedupe_paths(paths: list[Path]) -> list[Path]:
    seen: set[str] = set()
    deduped: list[Path] = []
    for path in paths:
        key = str(path)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(path)
    return deduped


def _int_or_none(value: object) -> int | None:
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        try:
            return int(value)
        except ValueError:
            return None
    return None
