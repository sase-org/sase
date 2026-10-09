"""Stdlib-only structured failure facts for the agent runner.

This module is imported at runner boot and runs inside the dying runner,
whose interpreter may already be torn by a mid-run code swap. It therefore
uses only the standard library (plus modules already imported at boot) and
performs no function-local imports. An AST test enforces both rules.
"""

from __future__ import annotations

import datetime
import re
import traceback
import types
from typing import Any

SCHEMA_VERSION = 1

#: At most this many exception-chain links are recorded, outermost first.
MAX_CHAIN_LINKS = 8

#: At most this many traceback frames are recorded, innermost last.
MAX_FRAMES = 64

#: An individual exception message is truncated to this many characters.
MAX_MESSAGE_CHARS = 2048

#: At most this many lifecycle history entries are kept (mirrors breadcrumbs).
MAX_HISTORY_ENTRIES = 16

#: Exception type names that make a failure skew-suspect on their own.
_SKEW_TYPE_NAMES = frozenset(
    {
        "ImportError",
        "ModuleNotFoundError",
        "AttributeError",
        "SyntaxError",
        "IndentationError",
    }
)

#: Message fragments (matched case-insensitively) from the Tier 1-3
#: families: torn Python code, Rust binding/wire skew, data-format skew.
_SKEW_MESSAGE_PATTERNS = (
    "cannot import name",
    "no module named",
    "partially initialized module",
    "has no attribute",
    "does not expose binding",
    "wire schema mismatch",
    "wire is stale",
    "sase_core_rs",
    "was written by a newer",
    "unknown sase version",
    "newer or unknown",
    "format this process does not understand",
)

_MISSING_SYMBOL_PATTERN = re.compile(r"cannot import name ['\"]([^'\"]+)['\"]")


def _utc_now_iso() -> str:
    return datetime.datetime.now(datetime.UTC).isoformat()


def _truncate_message(value: object) -> str:
    try:
        text = str(value)
    except Exception:
        return "<unprintable>"
    if len(text) > MAX_MESSAGE_CHARS:
        return text[:MAX_MESSAGE_CHARS]
    return text


def _walk_chain(exc: BaseException) -> list[BaseException]:
    """Return the cause/context chain, outermost first, with cycle detection."""
    chain: list[BaseException] = []
    seen: set[int] = set()
    current: BaseException | None = exc
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        chain.append(current)
        if len(chain) >= MAX_CHAIN_LINKS:
            break
        cause = current.__cause__
        if cause is not None:
            current = cause
        else:
            current = current.__context__
    return chain


def _chain_link(exc: BaseException) -> dict[str, Any]:
    exc_type = type(exc)
    return {
        "type": exc_type.__name__,
        "qualname": exc_type.__qualname__,
        "module": exc_type.__module__,
        "message": _truncate_message(exc),
    }


def _extract_import_error(
    chain: list[BaseException],
) -> dict[str, Any] | None:
    """Return the innermost ImportError's structured fields, if any."""
    target: ImportError | None = None
    for link in chain:
        if isinstance(link, ImportError):
            target = link
    if target is None:
        return None
    name = target.name if isinstance(target.name, str) else None
    path = target.path if isinstance(target.path, str) else None
    missing_symbol: str | None = None
    try:
        match = _MISSING_SYMBOL_PATTERN.search(str(target))
    except Exception:
        match = None
    if match is not None:
        missing_symbol = match.group(1)
    return {"name": name, "path": path, "missing_symbol": missing_symbol}


def _extract_attribute_error(
    chain: list[BaseException],
) -> dict[str, Any] | None:
    """Return module-target AttributeError fields, else None.

    Only an attribute lookup against a module itself can be update skew;
    ``obj.attr`` on an arbitrary instance is an ordinary bug.
    """
    target: AttributeError | None = None
    for link in chain:
        if isinstance(link, AttributeError):
            target = link
    if target is None:
        return None
    obj = getattr(target, "obj", None)
    if not isinstance(obj, types.ModuleType):
        return None
    attribute = getattr(target, "name", None)
    return {
        "module": getattr(obj, "__name__", None),
        "attribute": attribute if isinstance(attribute, str) else None,
    }


def _extract_frames(exc: BaseException) -> list[dict[str, Any]]:
    """Return traceback frames, innermost last, bounded to the tail."""
    try:
        summaries = traceback.extract_tb(exc.__traceback__)
    except Exception:
        return []
    frames: list[dict[str, Any]] = []
    for summary in summaries:
        try:
            frames.append(
                {
                    "file": summary.filename,
                    "function": summary.name,
                    "line": summary.lineno,
                }
            )
        except Exception:
            continue
    if len(frames) > MAX_FRAMES:
        return frames[-MAX_FRAMES:]
    return frames


def _text_looks_like_skew(*texts: str | None) -> bool:
    for text in texts:
        if not text:
            continue
        try:
            lowered = text.lower()
        except Exception:
            continue
        for pattern in _SKEW_MESSAGE_PATTERNS:
            if pattern in lowered:
                return True
    return False


def facts_look_like_update_skew(facts: dict[str, Any]) -> bool:
    """Cheap, deliberately over-inclusive update-skew prefilter.

    Matches the Tier 1-3 families (torn Python code, Rust binding/wire
    skew, data-format skew) without any origin scoping: a workspace
    ImportError still counts as suspect here, and the authoritative
    classifier sorts it out later.
    """
    if not isinstance(facts, dict):
        return False
    if facts.get("import_error") is not None:
        return True
    if facts.get("attribute_error") is not None:
        return True
    chain = facts.get("exception_chain")
    if isinstance(chain, list):
        for link in chain:
            if not isinstance(link, dict):
                continue
            link_type = link.get("type")
            if isinstance(link_type, str) and link_type in _SKEW_TYPE_NAMES:
                return True
            if _text_looks_like_skew(link.get("message")):
                return True
    if _text_looks_like_skew(facts.get("error_text")):
        return True
    return False


def capture_failure_facts(
    exc: BaseException | None,
    *,
    phase: str | None,
    error_text: str | None = None,
    traceback_text: str | None = None,
) -> dict[str, Any]:
    """Capture bounded, structured failure facts. Never raises.

    With a live exception, records the cause/context chain (so a
    double-wrapped provider ImportError stays visible), traceback frames,
    and the ImportError/AttributeError extractions. Without one (loop-level
    and shutdown-path failures), records phase-only facts, with
    ``skew_suspect`` derived from any supplied error text.
    """
    try:
        return _capture_failure_facts(
            exc,
            phase=phase,
            error_text=error_text,
            traceback_text=traceback_text,
        )
    except Exception:
        try:
            return {
                "schema_version": SCHEMA_VERSION,
                "captured_at": _utc_now_iso(),
                "lifecycle_phase": phase,
                "exception_chain": [],
                "import_error": None,
                "attribute_error": None,
                "frames": [],
                "last_frame_file": None,
                "skew_suspect": False,
                "error_text": None,
            }
        except Exception:
            return {"schema_version": SCHEMA_VERSION}


def _capture_failure_facts(
    exc: BaseException | None,
    *,
    phase: str | None,
    error_text: str | None,
    traceback_text: str | None,
) -> dict[str, Any]:
    chain = _walk_chain(exc) if exc is not None else []
    links = [_chain_link(link) for link in chain]
    import_error = _extract_import_error(chain) if chain else None
    attribute_error = _extract_attribute_error(chain) if chain else None
    frames = _extract_frames(exc) if exc is not None else []
    last_frame_file: str | None = None
    if frames:
        candidate = frames[-1].get("file")
        if isinstance(candidate, str):
            last_frame_file = candidate
    facts: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "captured_at": _utc_now_iso(),
        "lifecycle_phase": phase,
        "exception_chain": links,
        "import_error": import_error,
        "attribute_error": attribute_error,
        "frames": frames,
        "last_frame_file": last_frame_file,
        "skew_suspect": False,
        "error_text": error_text,
    }
    if facts_look_like_update_skew(facts) or _text_looks_like_skew(
        error_text, traceback_text
    ):
        facts["skew_suspect"] = True
    return facts
