"""Tests for update receipt persistence and decoding."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

from sase.ace._update_receipt_codec import receipt_from_json
from sase.ace.comprehensive_update import (
    ComprehensiveSaseUpdateResult,
    ComprehensiveUpdateResult,
    SaseUpdateResultStatus,
)
from sase.ace.update_receipt import (
    _ProviderUpdateReceiptResult,
    RepoCommitGroup,
    UpdateToastReceipt,
    UpdateVersionTransition,
    build_update_receipt,
    read_and_clear_pending_update_toast,
    write_pending_update_toast,
)
from sase.agent_clis.models import AgentCliUpdateResult, UpdateResultStatus
from sase.dev_update.models import RepoCommit, RepoCommitLog, RepoDiffStat
from sase.uv_tool.render import UpdateOutcome, UpdateSummary
from sase.uv_tool.runner import ChangeKind


def test_pending_update_toast_round_trips_and_consumes_once(tmp_path: Path) -> None:
    receipt = UpdateToastReceipt(
        kind="managed",
        created_at=100.0,
        primary=UpdateVersionTransition("sase", "0.5.0", "0.6.0"),
        plugins=(UpdateVersionTransition("sase-github", "1.0.0", "1.1.0"),),
        dependency_count=2,
    )
    receipt_file = tmp_path / "pending.json"

    with patch("sase.ace.update_receipt._PENDING_UPDATE_TOAST_FILE", receipt_file):
        assert write_pending_update_toast(receipt) is True
        assert read_and_clear_pending_update_toast(now=101.0) == receipt
        assert not receipt_file.exists()
        assert read_and_clear_pending_update_toast(now=101.0) is None


def test_pending_update_toast_round_trips_optional_diffstats(
    tmp_path: Path,
) -> None:
    receipt = UpdateToastReceipt(
        kind="dev",
        created_at=100.0,
        primary=UpdateVersionTransition(
            "sase",
            "0.5.0",
            "0.6.0",
            diffstat=RepoDiffStat(files_changed=12, insertions=1234, deletions=567),
        ),
        plugins=(
            UpdateVersionTransition(
                "sase-github",
                "1.0.0",
                "1.1.0",
                diffstat=RepoDiffStat(files_changed=2, insertions=4, deletions=1),
            ),
        ),
        plugin_overflow=1,
        plugin_overflow_diffstat=RepoDiffStat(
            files_changed=1,
            insertions=0,
            deletions=0,
        ),
        dependency_count=2,
    )
    receipt_file = tmp_path / "pending.json"

    with patch("sase.ace.update_receipt._PENDING_UPDATE_TOAST_FILE", receipt_file):
        assert write_pending_update_toast(receipt) is True
        assert read_and_clear_pending_update_toast(now=101.0) == receipt


def test_pending_update_toast_round_trips_commit_groups(tmp_path: Path) -> None:
    receipt = UpdateToastReceipt(
        kind="dev",
        created_at=100.0,
        primary=UpdateVersionTransition("sase", "0.5.0", "0.6.0"),
        commit_groups=(
            RepoCommitGroup(
                label="sase",
                commits=RepoCommitLog(
                    total=3,
                    commits=(
                        RepoCommit("abc1234", "feat: grouped commit toast"),
                        RepoCommit("def5678", "fix: preserve provider results"),
                    ),
                ),
            ),
        ),
        commit_group_overflow=2,
    )
    receipt_file = tmp_path / "pending.json"

    with patch("sase.ace.update_receipt._PENDING_UPDATE_TOAST_FILE", receipt_file):
        assert write_pending_update_toast(receipt) is True
        assert read_and_clear_pending_update_toast(now=101.0) == receipt


def test_comprehensive_receipt_round_trips_provider_outcomes(
    tmp_path: Path,
) -> None:
    summary = UpdateSummary(
        outcomes=(
            UpdateOutcome(
                "sase",
                "primary",
                ChangeKind.UPGRADED,
                old_version="0.5.0",
                new_version="0.6.0",
            ),
        )
    )
    result = ComprehensiveUpdateResult(
        sase=ComprehensiveSaseUpdateResult(
            SaseUpdateResultStatus.UPDATED,
            "updated sase",
            summary,
        ),
        provider_results=(
            AgentCliUpdateResult(
                name="claude",
                display_name="Claude Code",
                status=UpdateResultStatus.UPDATED,
                old_version="1.0.0",
                new_version="1.1.0",
                command=("claude", "update"),
                docs_url="https://example.com/claude",
            ),
            AgentCliUpdateResult(
                name="codex",
                display_name="Codex CLI",
                status=UpdateResultStatus.SKIPPED,
                old_version="0.9.0",
                new_version="0.9.0",
                command=None,
                docs_url="https://example.com/codex",
                suggested_command=("brew", "upgrade", "codex"),
                reason="manual upgrade required",
            ),
        ),
    )
    receipt = build_update_receipt(result, created_at=100.0)

    assert receipt is not None
    assert receipt.provider_results == (
        _ProviderUpdateReceiptResult(
            name="claude",
            display_name="Claude Code",
            status="updated",
            old_version="1.0.0",
            new_version="1.1.0",
            docs_url="https://example.com/claude",
            command=("claude", "update"),
        ),
        _ProviderUpdateReceiptResult(
            name="codex",
            display_name="Codex CLI",
            status="skipped",
            old_version="0.9.0",
            new_version="0.9.0",
            reason="manual upgrade required",
            docs_url="https://example.com/codex",
            suggested_command=("brew", "upgrade", "codex"),
        ),
    )
    receipt_file = tmp_path / "pending.json"
    with patch("sase.ace.update_receipt._PENDING_UPDATE_TOAST_FILE", receipt_file):
        assert write_pending_update_toast(receipt)
        assert read_and_clear_pending_update_toast(now=101.0) == receipt


def test_provider_only_comprehensive_result_does_not_create_restart_receipt() -> None:
    result = ComprehensiveUpdateResult(
        sase=ComprehensiveSaseUpdateResult(
            SaseUpdateResultStatus.ALREADY_CURRENT,
            "already current",
        ),
        provider_results=(
            AgentCliUpdateResult(
                name="claude",
                display_name="Claude Code",
                status=UpdateResultStatus.UPDATED,
                old_version="1.0.0",
                new_version="1.1.0",
                command=("claude", "update"),
                docs_url=None,
            ),
        ),
    )

    assert build_update_receipt(result, created_at=100.0) is None


def test_pending_update_toast_round_trips_install_and_uninstall_transitions(
    tmp_path: Path,
) -> None:
    receipt = UpdateToastReceipt(
        kind="managed",
        created_at=100.0,
        primary=None,
        plugins=(
            UpdateVersionTransition("sase-nvim", None, "2.0.0"),
            UpdateVersionTransition("sase-github", "1.2.0", None),
        ),
    )
    receipt_file = tmp_path / "pending.json"

    with patch("sase.ace.update_receipt._PENDING_UPDATE_TOAST_FILE", receipt_file):
        assert write_pending_update_toast(receipt) is True
        assert read_and_clear_pending_update_toast(now=101.0) == receipt


def test_legacy_pending_update_toast_without_diffstats_decodes(
    tmp_path: Path,
) -> None:
    receipt_file = tmp_path / "pending.json"
    receipt_file.write_text(
        json.dumps(
            {
                "format": 1,
                "created_at": 100.0,
                "kind": "dev",
                "primary": {"name": "sase", "old": "0.5.0", "new": "0.6.0"},
                "plugins": [{"name": "sase-github", "old": "1.0.0", "new": "1.1.0"}],
                "plugin_overflow": 0,
                "dependency_count": 0,
            }
        ),
        encoding="utf-8",
    )

    with patch("sase.ace.update_receipt._PENDING_UPDATE_TOAST_FILE", receipt_file):
        receipt = read_and_clear_pending_update_toast(now=101.0)

    assert receipt is not None
    assert receipt.primary is not None
    assert receipt.primary.diffstat is None
    assert receipt.plugins[0].diffstat is None
    assert receipt.plugin_overflow_diffstat is None


def test_format_two_receipt_still_decodes_provider_results(tmp_path: Path) -> None:
    receipt_file = tmp_path / "pending.json"
    receipt_file.write_text(
        json.dumps(
            {
                "format": 2,
                "created_at": 100.0,
                "kind": "dev",
                "primary": {"name": "sase", "old": "0.5.0", "new": "0.6.0"},
                "plugins": [],
                "plugin_overflow": 0,
                "dependency_count": 0,
                "provider_results": [
                    {
                        "name": "codex",
                        "display_name": "Codex CLI",
                        "status": "updated",
                        "old_version": "1.0.0",
                        "new_version": "1.1.0",
                    }
                ],
                "provider_overflow": 0,
            }
        ),
        encoding="utf-8",
    )

    with patch("sase.ace.update_receipt._PENDING_UPDATE_TOAST_FILE", receipt_file):
        receipt = read_and_clear_pending_update_toast(now=101.0)

    assert receipt is not None
    assert receipt.commit_groups == ()
    assert receipt.provider_results == (
        _ProviderUpdateReceiptResult(
            name="codex",
            display_name="Codex CLI",
            status="updated",
            old_version="1.0.0",
            new_version="1.1.0",
        ),
    )


def test_malformed_commit_group_rejects_receipt() -> None:
    assert (
        receipt_from_json(
            {
                "format": 3,
                "created_at": 100.0,
                "kind": "dev",
                "primary": {"name": "sase", "old": "0.5.0", "new": "0.6.0"},
                "plugins": [],
                "plugin_overflow": 0,
                "dependency_count": 0,
                "commit_groups": [
                    {
                        "label": "sase",
                        "total": 1,
                        "commits": [{"short_sha": "abc1234", "subject": ""}],
                    }
                ],
                "commit_group_overflow": 0,
                "provider_results": [],
                "provider_overflow": 0,
            }
        )
        is None
    )


def test_missing_pending_update_toast_returns_none(tmp_path: Path) -> None:
    with patch(
        "sase.ace.update_receipt._PENDING_UPDATE_TOAST_FILE",
        tmp_path / "missing.json",
    ):
        assert read_and_clear_pending_update_toast(now=100.0) is None


def test_corrupt_pending_update_toast_is_ignored_and_deleted(tmp_path: Path) -> None:
    receipt_file = tmp_path / "pending.json"
    receipt_file.write_text("{not json", encoding="utf-8")

    with patch("sase.ace.update_receipt._PENDING_UPDATE_TOAST_FILE", receipt_file):
        assert read_and_clear_pending_update_toast(now=100.0) is None
        assert not receipt_file.exists()


def test_non_object_pending_update_toast_is_ignored_and_deleted(tmp_path: Path) -> None:
    receipt_file = tmp_path / "pending.json"
    receipt_file.write_text('"sase"', encoding="utf-8")

    with patch("sase.ace.update_receipt._PENDING_UPDATE_TOAST_FILE", receipt_file):
        assert read_and_clear_pending_update_toast(now=100.0) is None
        assert not receipt_file.exists()


def test_unknown_format_pending_update_toast_is_ignored_and_deleted(
    tmp_path: Path,
) -> None:
    receipt_file = tmp_path / "pending.json"
    receipt_file.write_text(
        json.dumps(
            {
                "format": 99,
                "created_at": 100.0,
                "kind": "managed",
                "primary": {"name": "sase", "old": "0.5.0", "new": "0.6.0"},
                "plugins": [],
                "plugin_overflow": 0,
                "dependency_count": 0,
            }
        ),
        encoding="utf-8",
    )

    with patch("sase.ace.update_receipt._PENDING_UPDATE_TOAST_FILE", receipt_file):
        assert read_and_clear_pending_update_toast(now=101.0) is None
        assert not receipt_file.exists()


def test_stale_pending_update_toast_is_ignored_and_deleted(tmp_path: Path) -> None:
    receipt = UpdateToastReceipt(
        kind="managed",
        created_at=100.0,
        primary=UpdateVersionTransition("sase", "0.5.0", "0.6.0"),
    )
    receipt_file = tmp_path / "pending.json"

    with patch("sase.ace.update_receipt._PENDING_UPDATE_TOAST_FILE", receipt_file):
        assert write_pending_update_toast(receipt) is True
        assert read_and_clear_pending_update_toast(now=100.0 + 31 * 60) is None
        assert not receipt_file.exists()
