"""Commit result marker helpers for builtin@commit repair support."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
import json
from pathlib import Path
from typing import Any

from sase.core.finalizer_wire import FinalizerOutcomeEvidenceWire
from sase.finalizers.commit_repair_common import bound_stream
from sase.llm_provider.commit_finalizer_git import normalize_path
from sase.llm_provider.commit_finalizer_types import DirtyRepo


def load_commit_results(artifacts: Path | None) -> list[dict[str, Any]]:
    if artifacts is None:
        return []
    try:
        payload = json.loads(
            (artifacts / "commit_results.json").read_text(encoding="utf-8")
        )
    except (OSError, json.JSONDecodeError):
        return []
    if not isinstance(payload, list):
        return []
    return [item for item in payload if isinstance(item, dict)]


def new_commit_markers(
    before: Sequence[Mapping[str, Any]],
    after: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    before_keys = {_marker_key(item) for item in before}
    return [dict(item) for item in after if _marker_key(item) not in before_keys]


def marker_matches_repo(marker: Mapping[str, Any], repo: DirtyRepo) -> bool:
    cwd = marker.get("cwd")
    return isinstance(cwd, str) and normalize_path(cwd) == normalize_path(repo.path)


def marker_is_unpushed(marker: Mapping[str, Any]) -> bool:
    if marker.get("settled") or marker.get("superseded_by"):
        return False
    return marker.get("pushed") is False and bool(marker.get("commit_sha"))


def marker_evidence(
    marker: Mapping[str, Any],
) -> list[FinalizerOutcomeEvidenceWire]:
    evidence: list[FinalizerOutcomeEvidenceWire] = []
    for key in (
        "cwd",
        "result",
        "commit_sha",
        "commit_tree",
        "entry_id",
        "push_error",
    ):
        value = marker.get(key)
        if isinstance(value, str) and value:
            evidence.append(FinalizerOutcomeEvidenceWire(kind=key, value=value))
    if not any(item.kind == "commit_sha" for item in evidence):
        evidence.append(
            FinalizerOutcomeEvidenceWire(
                kind="warning",
                value="commit_results entry omitted commit_sha",
            )
        )
    if not any(item.kind == "commit_tree" for item in evidence):
        evidence.append(
            FinalizerOutcomeEvidenceWire(
                kind="warning",
                value="commit_results entry omitted commit_tree",
            )
        )
    pushed = marker.get("pushed")
    if isinstance(pushed, bool):
        evidence.append(
            FinalizerOutcomeEvidenceWire(
                kind="pushed",
                value="true" if pushed else "false",
            )
        )
    dispatch_error = marker.get("dispatch_error")
    if isinstance(dispatch_error, str) and dispatch_error:
        evidence.append(
            FinalizerOutcomeEvidenceWire(
                kind="dispatch_error",
                value=bound_stream(dispatch_error),
            )
        )
    return evidence


def _marker_key(marker: Mapping[str, Any]) -> tuple[Any, ...]:
    return (
        marker.get("cwd"),
        marker.get("result"),
        marker.get("commit_sha"),
        marker.get("commit_tree"),
        marker.get("entry_id"),
    )


__all__ = [
    "load_commit_results",
    "marker_evidence",
    "marker_is_unpushed",
    "marker_matches_repo",
    "new_commit_markers",
]
