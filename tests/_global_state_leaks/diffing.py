"""Classify differences between global-state snapshots."""

from __future__ import annotations

from collections import Counter

from tests._global_state_leaks.fingerprints import (
    LIVE_CONFIG_TOKEN_REFRESH_THREADS_GLOBAL,
)
from tests._global_state_leaks.models import (
    _CacheFingerprint,
    _Change,
    _Diff,
    _Snapshot,
    _ValueFingerprint,
)


def _diff_snapshots(before: _Snapshot, after: _Snapshot) -> _Diff:
    poisoning: list[_Change] = []
    warming_counts: Counter[str] = Counter()
    cooling_counts: Counter[str] = Counter()
    invalidation_counts: Counter[str] = Counter()

    for name in sorted(set(before.globals) | set(after.globals)):
        before_value = before.globals.get(name)
        after_value = after.globals.get(name)
        classification = _classify_global_change(name, before_value, after_value)
        if classification == "none":
            continue
        if classification == "warming":
            warming_counts["global"] += 1
            continue
        if classification == "cooling":
            cooling_counts["global"] += 1
            continue
        if classification == "invalidation":
            invalidation_counts["global"] += 1
            continue
        poisoning.append(
            _Change(
                kind="global",
                name=name,
                reason=classification,
                before=_public_fingerprint(before_value),
                after=_public_fingerprint(after_value),
            )
        )

    for name in sorted(set(before.caches) | set(after.caches)):
        before_cache = before.caches.get(name)
        after_cache = after.caches.get(name)
        classification = _classify_cache_change(before_cache, after_cache)
        if classification == "none":
            continue
        if classification == "warming":
            warming_counts["cache"] += 1
            continue
        if classification == "cooling":
            cooling_counts["cache"] += 1
            continue
        if classification == "invalidation":
            invalidation_counts["cache"] += 1
            continue
        poisoning.append(
            _Change(
                kind="cache",
                name=name,
                reason=classification,
                before=_public_cache(before_cache),
                after=_public_cache(after_cache),
            )
        )

    ambient_changes, ambient_warming_counts, ambient_cooling_counts = _ambient_changes(
        before, after
    )
    poisoning.extend(ambient_changes)
    warming_counts.update(ambient_warming_counts)
    cooling_counts.update(ambient_cooling_counts)

    return _Diff(
        poisoning=tuple(poisoning),
        warming_counts=dict(warming_counts),
        cooling_counts=dict(cooling_counts),
        invalidation_counts=dict(invalidation_counts),
    )


def _classify_global_change(
    name: str,
    before: _ValueFingerprint | None,
    after: _ValueFingerprint | None,
) -> str:
    if before == after:
        return "none"
    if name == LIVE_CONFIG_TOKEN_REFRESH_THREADS_GLOBAL:
        if after is None or _is_canonical_cold(after):
            return "cooling"
        return "live-config-token-refresh-thread"
    if before is None:
        return "warming"
    if before.kind == "none" and after is None:
        return "cooling"
    if after is None:
        return "changed-to-untracked-or-deleted"
    if before.kind == "none" and after.kind != "none":
        return "warming"
    if _is_canonical_cold(after):
        return "cooling"
    if before.kind != after.kind:
        if _is_cache_like_global_name(name):
            return "invalidation"
        return "changed-kind"
    if _is_collection_warming(before, after):
        return "warming"
    if _is_cache_like_global_name(name):
        return "invalidation"
    return "changed-value"


def _is_cache_like_global_name(name: str) -> bool:
    attr_name = name.rsplit(".", maxsplit=1)[-1].lower()
    return (
        "cache" in attr_name
        or "memo" in attr_name
        or attr_name
        in {
            "_cleaned_artifact_dirs",
            "_context",
            "_last_saved_dismissed_generation",
        }
    )


def _is_collection_warming(
    before: _ValueFingerprint,
    after: _ValueFingerprint,
) -> bool:
    if before.kind == "dict" and after.kind == "dict":
        return before.entries.issubset(after.entries)
    if before.kind in {"set", "frozenset"} and after.kind == before.kind:
        return before.entries.issubset(after.entries)
    if before.kind == "list" and after.kind == "list":
        return after.sequence[: len(before.sequence)] == before.sequence
    return False


def _is_canonical_cold(value: _ValueFingerprint) -> bool:
    if value.kind == "none":
        return True
    if value.kind in {"dict", "set", "frozenset", "list"}:
        return value.length == 0
    return False


def _classify_cache_change(
    before: _CacheFingerprint | None,
    after: _CacheFingerprint | None,
) -> str:
    if before == after:
        return "none"
    if before is None:
        return "warming"
    if after is None:
        return "invalidation"
    if before.maxsize != after.maxsize:
        return "invalidation"
    if after.currsize == 0 and before.currsize > 0:
        return "cooling"
    if after.currsize < before.currsize:
        return "invalidation"
    if after.hits < before.hits or after.misses < before.misses:
        return "invalidation"
    return "warming"


def _ambient_changes(
    before: _Snapshot, after: _Snapshot
) -> tuple[list[_Change], Counter[str], Counter[str]]:
    changes: list[_Change] = []
    warming_counts: Counter[str] = Counter()
    cooling_counts: Counter[str] = Counter()
    if before.environ != after.environ:
        changes.append(
            _Change(
                kind="environment",
                name="os.environ",
                reason="environment-changed",
                before=_public_environment(before.environ),
                after=_public_environment(after.environ),
                details=_environment_delta(before.environ, after.environ),
            )
        )
    if before.sys_path != after.sys_path:
        classification = _classify_global_change(
            "sys.path", before.sys_path, after.sys_path
        )
        if classification == "warming":
            warming_counts["sys_path"] += 1
        elif classification == "cooling":
            cooling_counts["sys_path"] += 1
        else:
            changes.append(
                _Change(
                    kind="sys_path",
                    name="sys.path",
                    reason="sys-path-changed",
                    before=before.sys_path.public(),
                    after=after.sys_path.public(),
                )
            )
    if before.cwd != after.cwd:
        changes.append(
            _Change(
                kind="cwd",
                name="os.getcwd()",
                reason="working-directory-changed",
                before={"kind": "cwd", "value": before.cwd},
                after={"kind": "cwd", "value": after.cwd},
            )
        )
    return changes, warming_counts, cooling_counts


def _public_fingerprint(value: _ValueFingerprint | None) -> dict[str, object]:
    if value is None:
        return {"kind": "missing"}
    return value.public()


def _public_cache(value: _CacheFingerprint | None) -> dict[str, object]:
    if value is None:
        return {"kind": "missing"}
    payload: dict[str, object] = {"kind": "cache"}
    payload.update(value.public())
    return payload


def _public_environment(value: _ValueFingerprint) -> dict[str, object]:
    return {
        "kind": "environment",
        "digest": value.digest,
        "len": value.length or 0,
    }


def _environment_delta(
    before: _ValueFingerprint, after: _ValueFingerprint
) -> dict[str, object]:
    before_entries = _entry_digest_by_key(before)
    after_entries = _entry_digest_by_key(after)
    before_keys = set(before_entries)
    after_keys = set(after_entries)
    common_keys = before_keys & after_keys
    return {
        "added_keys": sorted(after_keys - before_keys),
        "removed_keys": sorted(before_keys - after_keys),
        "changed_keys": sorted(
            key for key in common_keys if before_entries[key] != after_entries[key]
        ),
    }


def _entry_digest_by_key(value: _ValueFingerprint) -> dict[str, str]:
    entries: dict[str, str] = {}
    for entry in value.entries:
        key, separator, digest = entry.partition("=")
        if separator:
            entries[key] = digest
    return entries
