"""Headless foundations for VCS repository completion inside workflow refs."""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal
from urllib.parse import quote

from sase import workspace_provider
from sase.config import load_merged_config
from sase.core.paths import sase_subdir
from sase.workspace_provider import VcsRepoCandidates, VcsRepoEntry

VCS_REPO_CATALOG_SCHEMA_VERSION = 1
VCS_REPO_CACHE_SCHEMA_VERSION = 1
DEFAULT_VCS_REPO_CACHE_TTL_SECONDS = 600
DEFAULT_VCS_REPO_MAX_REPOS = 200

VcsRepoCompletionStatus = Literal["ok", "error"]
VcsRepoCompletionErrorKind = Literal[
    "auth",
    "network",
    "not_found",
    "tool_missing",
    "unsupported_namespace",
    "unknown",
]
VcsRepoSeparator = Literal[":", "("]

VCS_REPO_GOLDEN_CURSOR = "<CURSOR>"

# Tuple shape: marked prompt, known workflow names, selected ref, expected prompt.
VCS_REPO_GOLDEN_VECTORS: tuple[
    tuple[str, tuple[str, ...], str, str],
    ...,
] = (
    (
        f"#gh:bbugyi200/{VCS_REPO_GOLDEN_CURSOR}",
        ("gh",),
        "bbugyi200/sase",
        "#gh:bbugyi200/sase ",
    ),
    (
        f"#gh:bbugyi200/sa{VCS_REPO_GOLDEN_CURSOR}",
        ("gh",),
        "bbugyi200/sase",
        "#gh:bbugyi200/sase ",
    ),
    (
        f"Fix #gh:bbugyi200/sa{VCS_REPO_GOLDEN_CURSOR} now",
        ("gh",),
        "bbugyi200/sase",
        "Fix #gh:bbugyi200/sase now",
    ),
    (
        f"#gh!!:bbugyi200/sa{VCS_REPO_GOLDEN_CURSOR}",
        ("gh",),
        "bbugyi200/sase",
        "#gh!!:bbugyi200/sase ",
    ),
    (
        f"#gh(bbugyi200/sa{VCS_REPO_GOLDEN_CURSOR}",
        ("gh",),
        "bbugyi200/sase",
        "#gh(bbugyi200/sase)",
    ),
    (
        f"#gh(bbugyi200/sa{VCS_REPO_GOLDEN_CURSOR}) next",
        ("gh",),
        "bbugyi200/sase",
        "#gh(bbugyi200/sase) next",
    ),
    (
        f"#gh??(bbugyi200/{VCS_REPO_GOLDEN_CURSOR}",
        ("gh",),
        "bbugyi200/sase",
        "#gh??(bbugyi200/sase)",
    ),
    (
        f"#gl:group/sub/re{VCS_REPO_GOLDEN_CURSOR}",
        ("gl",),
        "group/sub/repo",
        "#gl:group/sub/repo ",
    ),
    (
        f"#gh:bbugyi200/s{VCS_REPO_GOLDEN_CURSOR}asex",
        ("gh",),
        "bbugyi200/sase",
        "#gh:bbugyi200/sase ",
    ),
)


# pyvision: sdd/epics/202607/vcs_repo_slash_completion.md
@dataclass(frozen=True)
class VcsRepoCompletionConfig:
    """Configuration for VCS repository completion."""

    enabled: bool = True
    cache_ttl_seconds: int = DEFAULT_VCS_REPO_CACHE_TTL_SECONDS
    max_repos: int = DEFAULT_VCS_REPO_MAX_REPOS


@dataclass(frozen=True)
class VcsRepoTrigger:
    """A detected VCS repository completion context."""

    start: int
    end: int
    workflow: str
    separator: VcsRepoSeparator
    ref_start: int
    ref_end: int
    namespace: str
    query: str
    namespace_span: tuple[int, int]
    query_span: tuple[int, int]

    @property
    def span(self) -> tuple[int, int]:
        """Return the full workflow token span."""
        return (self.start, self.end)

    @property
    def value_span(self) -> tuple[int, int]:
        """Return the full ref-value span, excluding ``#tag:`` or ``#tag(...``."""
        return (self.ref_start, self.ref_end)


@dataclass(frozen=True)
class VcsRepoFetchResult:
    """Repository completion data after cache/fetch orchestration."""

    status: VcsRepoCompletionStatus
    error_kind: VcsRepoCompletionErrorKind | None = None
    message: str = ""
    provider_display: str = ""
    entries: tuple[VcsRepoEntry, ...] = ()
    stale: bool = False


@dataclass(frozen=True)
class _CachedRepoPayload:
    fetched_at: float
    provider_display: str
    entries: tuple[VcsRepoEntry, ...]


_MEMO_CACHE: dict[tuple[str, str], _CachedRepoPayload] = {}


def load_vcs_repo_completion_config(
    config: dict[str, Any] | None = None,
) -> VcsRepoCompletionConfig:
    """Return normalized VCS repository completion settings."""
    data = load_merged_config() if config is None else config
    section = data.get("vcs_repo_completion", {}) if isinstance(data, dict) else {}
    if not isinstance(section, dict):
        section = {}

    enabled = section.get("enabled", True)
    cache_ttl_seconds = _coerce_int(
        section.get("cache_ttl_seconds"),
        default=DEFAULT_VCS_REPO_CACHE_TTL_SECONDS,
        minimum=0,
    )
    max_repos = _coerce_int(
        section.get("max_repos"),
        default=DEFAULT_VCS_REPO_MAX_REPOS,
        minimum=1,
    )
    return VcsRepoCompletionConfig(
        enabled=enabled if isinstance(enabled, bool) else True,
        cache_ttl_seconds=cache_ttl_seconds,
        max_repos=max_repos,
    )


def _coerce_int(value: object, *, default: int, minimum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        return default
    return max(value, minimum)


def find_vcs_repo_trigger(
    prompt: str,
    cursor: int,
    workflow_names: set[str] | list[str] | tuple[str, ...],
) -> VcsRepoTrigger | None:
    """Detect a repository completion trigger inside a VCS workflow ref."""
    if cursor < 0 or cursor > len(prompt):
        return None

    known_names = tuple(
        sorted((name for name in workflow_names if name), key=len, reverse=True)
    )
    if not known_names:
        return None

    start = cursor
    while start > 0 and not prompt[start - 1].isspace():
        start -= 1

    if start >= len(prompt) or prompt[start] != "#":
        return None

    workflow = _match_workflow_name(prompt, start + 1, known_names)
    if workflow is None:
        return None

    pos = start + 1 + len(workflow)
    if prompt.startswith("!!", pos) or prompt.startswith("??", pos):
        pos += 2
    if pos >= len(prompt) or prompt[pos] not in {":", "("}:
        return None

    separator = prompt[pos]
    ref_start = pos + 1
    if cursor < ref_start:
        return None
    if separator == "(" and ")" in prompt[ref_start:cursor]:
        return None

    ref_end, token_end = _find_ref_end(prompt, cursor, separator)
    if cursor > ref_end:
        return None

    ref_before_cursor = prompt[ref_start:cursor]
    slash_offset = ref_before_cursor.rfind("/")
    if slash_offset < 0:
        return None

    full_ref = prompt[ref_start:ref_end]
    if "://" in full_ref:
        return None

    namespace = ref_before_cursor[:slash_offset]
    if not namespace or namespace[0] in {"~", "."}:
        return None

    query = ref_before_cursor[slash_offset + 1 :]
    query_start = ref_start + slash_offset + 1
    return VcsRepoTrigger(
        start=start,
        end=token_end,
        workflow=workflow,
        separator=separator,  # type: ignore[arg-type]
        ref_start=ref_start,
        ref_end=ref_end,
        namespace=namespace,
        query=query,
        namespace_span=(ref_start, ref_start + slash_offset),
        query_span=(query_start, cursor),
    )


def _match_workflow_name(
    prompt: str,
    start: int,
    workflow_names: tuple[str, ...],
) -> str | None:
    for name in workflow_names:
        if prompt.startswith(name, start):
            return name
    return None


def _find_ref_end(
    prompt: str,
    cursor: int,
    separator: str,
) -> tuple[int, int]:
    end = cursor
    if separator == "(":
        while end < len(prompt) and not prompt[end].isspace() and prompt[end] != ")":
            end += 1
        token_end = end + 1 if end < len(prompt) and prompt[end] == ")" else end
        return end, token_end

    while end < len(prompt) and not prompt[end].isspace():
        end += 1
    return end, end


def apply_vcs_repo_selection(
    prompt: str,
    trigger: VcsRepoTrigger,
    selected_ref: str,
) -> str:
    """Return *prompt* with *trigger*'s ref value replaced by *selected_ref*."""
    start, end = trigger.value_span
    before = prompt[:start]
    after = prompt[end:]
    if trigger.separator == "(":
        suffix = "" if after.startswith(")") else ")"
        return f"{before}{selected_ref}{suffix}{after}"

    suffix = "" if after.startswith(tuple(" \t\r\n")) else " "
    return f"{before}{selected_ref}{suffix}{after}"


def fetch_repo_candidates(
    workflow_type: str,
    namespace: str,
    *,
    config: VcsRepoCompletionConfig | None = None,
) -> VcsRepoFetchResult:
    """Fetch repository candidates using the shared memo/disk TTL cache."""
    settings = config or load_vcs_repo_completion_config()
    if not settings.enabled:
        return VcsRepoFetchResult(status="ok", entries=())

    key = (workflow_type, namespace)
    now = time.time()
    stale_payload: _CachedRepoPayload | None = None

    memo_payload = _MEMO_CACHE.get(key)
    if memo_payload is not None:
        if _is_fresh(memo_payload, now, settings.cache_ttl_seconds):
            return _result_from_cache(memo_payload)
        stale_payload = memo_payload

    cache_path = _cache_path(workflow_type, namespace)
    disk_payload = _read_cache_payload(cache_path)
    if disk_payload is not None:
        _MEMO_CACHE[key] = disk_payload
        if _is_fresh(disk_payload, now, settings.cache_ttl_seconds):
            return _result_from_cache(disk_payload)
        stale_payload = disk_payload

    fetched = workspace_provider.list_repo_candidates(workflow_type, namespace)
    entries = tuple(fetched.entries[: settings.max_repos])
    if fetched.status == "ok":
        payload = _CachedRepoPayload(
            fetched_at=now,
            provider_display=fetched.provider_display,
            entries=entries,
        )
        _MEMO_CACHE[key] = payload
        _write_cache_payload(cache_path, payload)
        return VcsRepoFetchResult(
            status="ok",
            provider_display=fetched.provider_display,
            entries=entries,
        )

    if stale_payload is not None:
        return VcsRepoFetchResult(
            status="error",
            error_kind=fetched.error_kind,
            message=fetched.message,
            provider_display=fetched.provider_display or stale_payload.provider_display,
            entries=stale_payload.entries[: settings.max_repos],
            stale=True,
        )

    return VcsRepoFetchResult(
        status="error",
        error_kind=fetched.error_kind,
        message=fetched.message,
        provider_display=fetched.provider_display,
        entries=entries,
    )


def peek_cached_repo_candidates(
    workflow_type: str,
    namespace: str,
    *,
    config: VcsRepoCompletionConfig | None = None,
) -> VcsRepoFetchResult | None:
    """Return fresh cached repo candidates without invoking a provider.

    This is the TUI hot-path helper: it may read the small on-disk cache file,
    but it never calls :func:`workspace_provider.list_repo_candidates`, so a
    completion menu can decide whether to render rows immediately or show a
    loading placeholder before scheduling a worker.
    """
    settings = config or load_vcs_repo_completion_config()
    if not settings.enabled:
        return VcsRepoFetchResult(status="ok", entries=())

    key = (workflow_type, namespace)
    now = time.time()
    memo_payload = _MEMO_CACHE.get(key)
    if memo_payload is not None and _is_fresh(
        memo_payload,
        now,
        settings.cache_ttl_seconds,
    ):
        return _result_from_cache(memo_payload)

    disk_payload = _read_cache_payload(_cache_path(workflow_type, namespace))
    if disk_payload is None:
        return None
    _MEMO_CACHE[key] = disk_payload
    if not _is_fresh(disk_payload, now, settings.cache_ttl_seconds):
        return None
    return _result_from_cache(disk_payload)


def filter_vcs_repo_entries(
    entries: list[VcsRepoEntry] | tuple[VcsRepoEntry, ...],
    query: str,
) -> list[VcsRepoEntry]:
    """Filter and rank repo entries for local presentation-layer narrowing."""
    needle = query.casefold()
    if needle:
        filtered = [entry for entry in entries if needle in entry.name.casefold()]
    else:
        filtered = list(entries)
    return sorted(filtered, key=lambda entry: _repo_sort_key(entry, needle))


def vcs_repo_catalog_response(request: dict[str, Any]) -> dict[str, object]:
    """Return the JSON-serializable helper-bridge repo catalog response."""
    _reject_unexpected_fields(request, {"namespace", "schema_version", "workflow"})
    schema_version = request.get("schema_version", VCS_REPO_CATALOG_SCHEMA_VERSION)
    if schema_version != VCS_REPO_CATALOG_SCHEMA_VERSION:
        raise ValueError("unsupported vcs-repo-catalog schema_version")

    workflow = _required_string(request.get("workflow"), "workflow")
    namespace = _required_string(request.get("namespace"), "namespace")
    settings = load_vcs_repo_completion_config()
    if not settings.enabled:
        return _response_payload(VcsRepoFetchResult(status="ok", entries=()))
    return _response_payload(
        fetch_repo_candidates(workflow, namespace, config=settings)
    )


def _response_payload(result: VcsRepoFetchResult) -> dict[str, object]:
    return {
        "schema_version": VCS_REPO_CATALOG_SCHEMA_VERSION,
        "status": result.status,
        "error_kind": result.error_kind,
        "message": result.message,
        "provider_display": result.provider_display,
        "stale": result.stale,
        "entries": [_entry_to_dict(entry) for entry in result.entries],
    }


def _result_from_cache(payload: _CachedRepoPayload) -> VcsRepoFetchResult:
    return VcsRepoFetchResult(
        status="ok",
        provider_display=payload.provider_display,
        entries=payload.entries,
    )


def _is_fresh(
    payload: _CachedRepoPayload,
    now: float,
    ttl_seconds: int,
) -> bool:
    return ttl_seconds > 0 and now - payload.fetched_at <= ttl_seconds


def _cache_path(workflow_type: str, namespace: str) -> Path:
    workflow_slug = quote(workflow_type, safe="")
    namespace_slug = quote(namespace, safe="")
    return sase_subdir("vcs_repo_cache") / workflow_slug / f"{namespace_slug}.json"


def _read_cache_payload(path: Path) -> _CachedRepoPayload | None:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(raw, dict):
        return None
    if raw.get("schema_version") != VCS_REPO_CACHE_SCHEMA_VERSION:
        return None
    fetched_at = raw.get("fetched_at")
    provider_display = raw.get("provider_display")
    raw_entries = raw.get("entries")
    if not isinstance(fetched_at, int | float):
        return None
    if not isinstance(provider_display, str) or not isinstance(raw_entries, list):
        return None
    entries = tuple(
        entry
        for entry in (_entry_from_dict(item) for item in raw_entries)
        if entry is not None
    )
    return _CachedRepoPayload(
        fetched_at=float(fetched_at),
        provider_display=provider_display,
        entries=entries,
    )


def _write_cache_payload(path: Path, payload: _CachedRepoPayload) -> None:
    data = {
        "schema_version": VCS_REPO_CACHE_SCHEMA_VERSION,
        "fetched_at": payload.fetched_at,
        "provider_display": payload.provider_display,
        "entries": [_entry_to_dict(entry) for entry in payload.entries],
    }
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = path.with_suffix(f"{path.suffix}.tmp")
        tmp_path.write_text(json.dumps(data, separators=(",", ":")), encoding="utf-8")
        tmp_path.replace(path)
    except OSError:
        return


def _entry_to_dict(entry: VcsRepoEntry) -> dict[str, object]:
    return {
        "name": entry.name,
        "ref": entry.ref,
        "description": entry.description,
        "visibility": entry.visibility,
        "is_fork": entry.is_fork,
        "is_archived": entry.is_archived,
        "pushed_at": entry.pushed_at,
    }


def _entry_from_dict(data: object) -> VcsRepoEntry | None:
    if not isinstance(data, dict):
        return None
    name = data.get("name")
    ref = data.get("ref")
    if not isinstance(name, str) or not isinstance(ref, str):
        return None
    description = data.get("description", "")
    visibility = data.get("visibility", "")
    pushed_at = data.get("pushed_at")
    return VcsRepoEntry(
        name=name,
        ref=ref,
        description=description if isinstance(description, str) else "",
        visibility=visibility if isinstance(visibility, str) else "",
        is_fork=data.get("is_fork") is True,
        is_archived=data.get("is_archived") is True,
        pushed_at=pushed_at if isinstance(pushed_at, str) else None,
    )


def _repo_sort_key(
    entry: VcsRepoEntry,
    query: str,
) -> tuple[int, int, float, str, str]:
    name = entry.name.casefold()
    prefix_rank = 0 if not query or name.startswith(query) else 1
    timestamp = _parse_pushed_at(entry.pushed_at)
    missing_timestamp_rank = 0 if timestamp is not None else 1
    timestamp_rank = -timestamp if timestamp is not None else 0.0
    return (prefix_rank, missing_timestamp_rank, timestamp_rank, name, entry.name)


def _parse_pushed_at(value: str | None) -> float | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    try:
        return parsed.timestamp()
    except OSError:
        return None


def _required_string(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} is required")
    return value.strip()


def _reject_unexpected_fields(request: dict[str, Any], allowed: set[str]) -> None:
    unexpected = sorted(set(request) - allowed)
    if unexpected:
        fields = ", ".join(unexpected)
        raise ValueError(f"unexpected request field(s): {fields}")


__all__ = [
    "DEFAULT_VCS_REPO_CACHE_TTL_SECONDS",
    "DEFAULT_VCS_REPO_MAX_REPOS",
    "VCS_REPO_CATALOG_SCHEMA_VERSION",
    "VCS_REPO_GOLDEN_CURSOR",
    "VCS_REPO_GOLDEN_VECTORS",
    "VcsRepoCompletionConfig",
    "VcsRepoFetchResult",
    "VcsRepoTrigger",
    "apply_vcs_repo_selection",
    "fetch_repo_candidates",
    "filter_vcs_repo_entries",
    "find_vcs_repo_trigger",
    "load_vcs_repo_completion_config",
    "peek_cached_repo_candidates",
    "vcs_repo_catalog_response",
]
