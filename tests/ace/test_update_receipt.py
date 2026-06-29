"""Tests for the ACE post-update toast receipt handoff."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

from sase.ace.update_receipt import (
    UpdateToastReceipt,
    UpdateVersionTransition,
    build_update_receipt,
    read_and_clear_pending_update_toast,
    write_pending_update_toast,
)
from sase.dev_update.models import DevUpdateOutcome, DevUpdateResult
from sase.uv_tool.render import UpdateOutcome, UpdateSummary
from sase.uv_tool.runner import ChangeKind
from sase.version._models import VersionPackageRecord


def _record(name: str, *, role: str = "plugin") -> VersionPackageRecord:
    return VersionPackageRecord(
        name=name,
        role=role,  # type: ignore[arg-type]
        display_version="0.1.0+1.gabc123def",
        distribution_version="0.1.0",
        source_version="0.1.0",
        import_module=None,
        import_path=None,
        code_directory=None,
        source_root=f"/repo/{name}",
        distribution_location=None,
        install_type="editable",
        git=None,
    )


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


def test_build_managed_update_receipt_caps_plugins_and_counts_dependencies() -> None:
    summary = UpdateSummary(
        outcomes=(
            UpdateOutcome(
                "sase",
                "primary",
                ChangeKind.UPGRADED,
                old_version="0.5.0",
                new_version="0.6.0",
            ),
            UpdateOutcome(
                "sase-github",
                "plugin",
                ChangeKind.UPGRADED,
                old_version="1.0.0",
                new_version="1.1.0",
            ),
            UpdateOutcome(
                "sase-telegram",
                "plugin",
                ChangeKind.UPGRADED,
                old_version="1.0.0",
                new_version="1.1.0",
            ),
            UpdateOutcome(
                "sase-nvim",
                "plugin",
                ChangeKind.UPGRADED,
                old_version="1.0.0",
                new_version="1.1.0",
            ),
            UpdateOutcome(
                "sase-extra",
                "plugin",
                ChangeKind.UPGRADED,
                old_version="1.0.0",
                new_version="1.1.0",
            ),
            UpdateOutcome(
                "rich",
                "dependency",
                ChangeKind.UPGRADED,
                old_version="13.0.0",
                new_version="14.0.0",
            ),
        )
    )

    receipt = build_update_receipt(summary, created_at=123.0)

    assert receipt == UpdateToastReceipt(
        kind="managed",
        created_at=123.0,
        primary=UpdateVersionTransition("sase", "0.5.0", "0.6.0"),
        plugins=(
            UpdateVersionTransition("sase-github", "1.0.0", "1.1.0"),
            UpdateVersionTransition("sase-telegram", "1.0.0", "1.1.0"),
            UpdateVersionTransition("sase-nvim", "1.0.0", "1.1.0"),
        ),
        plugin_overflow=1,
        dependency_count=1,
    )


def test_build_managed_update_receipt_returns_none_for_no_updates() -> None:
    summary = UpdateSummary(
        outcomes=(
            UpdateOutcome(
                "sase",
                "primary",
                ChangeKind.UNCHANGED,
                new_version="0.6.0",
            ),
        )
    )

    assert build_update_receipt(summary, created_at=123.0) is None


def test_build_dev_update_receipt_uses_git_versions() -> None:
    result = DevUpdateResult(
        changed=True,
        outcomes=(
            DevUpdateOutcome(
                record=_record("sase", role="host"),
                status="updated",
                reason="behind upstream by 1 commit(s)",
                old_version="0.5.0+1.gabc123def",
                new_version="0.5.0+2.gdef456abc",
            ),
            DevUpdateOutcome(
                record=_record("sase-github"),
                status="updated",
                reason="behind upstream by 1 commit(s)",
                old_version="0.1.0+1.gabc123def",
                new_version="0.1.0+2.gdef456abc",
            ),
        ),
    )

    receipt = build_update_receipt(result, created_at=123.0)

    assert receipt == UpdateToastReceipt(
        kind="dev",
        created_at=123.0,
        primary=UpdateVersionTransition(
            "sase",
            "0.5.0+1.gabc123def",
            "0.5.0+2.gdef456abc",
        ),
        plugins=(
            UpdateVersionTransition(
                "sase-github",
                "0.1.0+1.gabc123def",
                "0.1.0+2.gdef456abc",
            ),
        ),
    )


def test_build_dev_update_receipt_returns_none_for_skipped_only() -> None:
    result = DevUpdateResult(
        changed=False,
        outcomes=(
            DevUpdateOutcome(
                record=_record("sase-github"),
                status="skipped",
                reason="checkout has local changes",
                old_version="0.1.0+1.gabc123def",
                new_version="0.1.0+2.gdef456abc",
            ),
        ),
    )

    assert build_update_receipt(result, created_at=123.0) is None
