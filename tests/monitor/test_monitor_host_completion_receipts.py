"""Commit-receipt matching for host completion settlement."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

from sase.monitor.delivery import (
    load_host_completion_receipt,
    persist_host_completion_receipt,
)

from ._host_completion import (
    make_intent,
    make_meta,
    patch_mod,
    patch_success_path,
    production_recovery,
    sandbox_home as sandbox_home,
    settle,
)

__all__ = [
    "test_completed_receipt_does_not_rerun_commit",
    "test_partial_repository_receipt_does_not_complete",
    "test_production_sha_receipt_completes_without_recovery",
]


def _production_commit_markers(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *repo_ids: str,
) -> list[dict[str, Any]]:
    """Mint markers exactly as production's ``write_result_marker`` writes them.

    A successful ``create_commit`` dispatch stores the short SHA as ``result``
    and the full SHA as ``commit_sha`` (never ``result == "ok"``). Markers are
    produced by the real writer into a scratch dir so their shape cannot drift
    from production; ``repo_id`` is attached afterwards because the receipt
    matcher reads it while the writer leaves repo identity to ``cwd``.
    """
    from sase.workflows.commit.commit_tracking import write_result_marker

    scratch = tmp_path / "scratch-markers"
    scratch.mkdir(exist_ok=True)
    monkeypatch.setenv("SASE_ARTIFACTS_DIR", str(scratch))
    monkeypatch.setenv("SASE_AGENT_TIMESTAMP", "run-1")
    try:
        markers: list[dict[str, Any]] = []
        for index, repo_id in enumerate(repo_ids):
            full_sha = ("ed03952a63" + f"{index:030x}")[:40]
            short_sha = full_sha[:10]
            written = write_result_marker(
                "create_commit",
                {"message": "fix: finish the change", "name": "cl", "bead_id": "b"},
                None,
                short_sha,
                None,
                commit_sha=full_sha,
                commit_tree="b" * 40,
                commit_cwd=str(tmp_path),
            )
            assert written
            stored = json.loads((scratch / "commit_results.json").read_text())
            marker = dict(stored[-1])
            assert marker["result"] == short_sha
            assert marker["commit_sha"] == full_sha
            marker["repo_id"] = repo_id
            markers.append(marker)
    finally:
        # The settle flow binds these itself; leaving scratch values behind
        # would trip its identity assertions.
        monkeypatch.delenv("SASE_ARTIFACTS_DIR", raising=False)
        monkeypatch.delenv("SASE_AGENT_TIMESTAMP", raising=False)
    return markers


def test_partial_repository_receipt_does_not_complete(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    intent = make_intent("repo-a", "repo-b")
    patch_success_path(monkeypatch, intent=intent)
    markers = _production_commit_markers(tmp_path, monkeypatch, "repo-a")
    patch_mod(
        monkeypatch,
        "load_commit_results",
        lambda *_a, **_k: markers,
    )
    patch_mod(
        monkeypatch,
        "invalidate_conditional_completion",
        lambda request: {**request["intent"], "status": "invalidated"},
    )
    recoveries: list[dict[str, Any]] = []

    result = settle(
        artifacts,
        make_meta(),
        launch_recovery=production_recovery(recoveries),
        release_claim=lambda *_a, **_k: None,
    )

    assert result is not None
    assert result.launch_result is not None
    assert result.launch_result.host_completed is not True
    assert result.launch_result.launched is True
    assert len(recoveries) == 1
    receipt = load_host_completion_receipt(artifacts)
    assert receipt is not None
    assert receipt["status"] == "recovery"
    assert receipt["reason"] == "outstanding_finalizer_actions"
    assert any(
        marker.get("repo_id") == "repo-a"
        for marker in receipt.get("commit_receipts") or []
    )


def test_production_sha_receipt_completes_without_recovery(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Regression for sase-1nh: SHA receipts must count as successful commits.

    Production's ``write_result_marker`` stores the short SHA as ``result``,
    so a matcher that only accepts ``result == "ok"`` leaves
    ``_successful_receipt_repo_ids`` empty and launches a pointless recovery
    successor after the stitch already landed. Settling with
    production-shaped SHA markers for every required repo must host-complete
    with no recovery launch.
    """
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    intent = make_intent("repo-a", "repo-b")
    patch_success_path(monkeypatch, intent=intent)
    markers = _production_commit_markers(tmp_path, monkeypatch, "repo-a", "repo-b")
    assert all(
        marker["result"] != "ok" and marker["commit_sha"].startswith(marker["result"])
        for marker in markers
    )
    patch_mod(
        monkeypatch,
        "load_commit_results",
        lambda *_a, **_k: markers,
    )
    recoveries: list[dict[str, Any]] = []
    releases: list[str] = []

    result = settle(
        artifacts,
        make_meta(),
        launch_recovery=production_recovery(recoveries, launched=False),
        release_claim=lambda _meta, _project: releases.append("released") or None,
    )

    assert result is not None
    assert result.launch_result is not None
    assert result.launch_result.host_completed is True
    assert recoveries == []
    assert releases == ["released"]
    receipt = load_host_completion_receipt(artifacts)
    assert receipt is not None
    assert receipt["status"] == "completed"


def test_completed_receipt_does_not_rerun_commit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    persist_host_completion_receipt(
        artifacts,
        {"schema_version": 1, "status": "completed", "published_message": "done"},
    )
    finalizers = MagicMock(side_effect=AssertionError("must not rerun finalizers"))
    patch_mod(monkeypatch, "run_finalizers", finalizers)
    patch_mod(monkeypatch, "update_meta_field", lambda *_a, **_k: None)
    recoveries: list[dict[str, Any]] = []

    result = settle(
        artifacts,
        make_meta(),
        launch_recovery=production_recovery(recoveries, launched=False),
        release_claim=lambda *_a, **_k: None,
        elapsed_seconds=12,
    )

    assert result is not None
    assert result.launch_result is not None
    assert result.launch_result.host_completed is True
    finalizers.assert_not_called()
    receipt = load_host_completion_receipt(artifacts)
    assert receipt is not None
    assert receipt["status"] == "completed"
