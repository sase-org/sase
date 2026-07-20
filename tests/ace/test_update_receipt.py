"""Tests for the ACE post-update toast receipt handoff."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

from sase.ace.update_receipt import (
    _ProviderUpdateReceiptResult,
    UpdateToastReceipt,
    UpdateVersionTransition,
    build_update_receipt,
    read_and_clear_pending_update_toast,
    write_pending_update_toast,
)
from sase.ace.comprehensive_update import (
    ComprehensiveSaseUpdateResult,
    ComprehensiveUpdateResult,
    SaseUpdateResultStatus,
)
from sase.agent_clis.models import AgentCliUpdateResult, UpdateResultStatus
from sase.dev_update.models import DevUpdateOutcome, DevUpdateResult
from sase.dev_update.models import RepoDiffStat
from sase.main.update_types import CombinedUpdateResult
from sase.plugins.operations import (
    InstallOutcome,
    InstallReady,
    ResolvedSpec,
    UninstallOutcome,
    UninstallReady,
    UpdateOutcome as PluginUpdateOutcome,
    UpdateReady,
)
from sase.uv_tool.render import UpdateOutcome, UpdateSummary
from sase.uv_tool.receipt import Requirement
from sase.uv_tool.runner import ChangeKind, UvChangeSet, UvPackageChange
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


def test_build_combined_core_only_receipt_is_managed_dependency_transition() -> None:
    result = CombinedUpdateResult(
        dev_result=DevUpdateResult(changed=False, outcomes=()),
        managed_summary=UpdateSummary(
            outcomes=(
                UpdateOutcome(
                    "sase-core-rs",
                    "dependency",
                    ChangeKind.UPGRADED,
                    old_version="0.4.0",
                    new_version="0.4.1",
                ),
            )
        ),
        elapsed=0.2,
    )

    assert build_update_receipt(result, created_at=123.0) == UpdateToastReceipt(
        kind="managed",
        created_at=123.0,
        primary=None,
        dependency_count=1,
    )


def test_build_plugin_install_receipt_uses_added_package_version() -> None:
    plan = InstallReady(
        spec=ResolvedSpec(
            requirement=Requirement.from_spec("sase-nvim"),
            display_name="nvim",
            source="catalog",
        ),
        argv=["uv", "tool", "install"],
    )
    outcome = InstallOutcome(
        plan=plan,
        change_set=UvChangeSet(
            changes=(
                UvPackageChange(
                    name="sase-nvim",
                    kind=ChangeKind.ADDED,
                    new_version="2.0.0",
                ),
            )
        ),
        groups=(),
        elapsed=0.0,
    )

    assert build_update_receipt(outcome, created_at=123.0) == UpdateToastReceipt(
        kind="managed",
        created_at=123.0,
        primary=None,
        plugins=(UpdateVersionTransition("sase-nvim", None, "2.0.0"),),
    )


def test_build_plugin_update_receipt_uses_target_transitions() -> None:
    plan = UpdateReady(
        argv=["uv", "tool", "install"],
        targets=("sase-github",),
        all_plugins=False,
    )
    outcome = PluginUpdateOutcome(
        plan=plan,
        change_set=UvChangeSet(
            changes=(
                UvPackageChange(
                    name="sase-github",
                    kind=ChangeKind.UPGRADED,
                    old_version="1.2.0",
                    new_version="1.3.0",
                ),
                UvPackageChange(
                    name="rich",
                    kind=ChangeKind.UPGRADED,
                    old_version="13.0.0",
                    new_version="14.0.0",
                ),
            )
        ),
        elapsed=0.0,
    )

    assert build_update_receipt(outcome, created_at=123.0) == UpdateToastReceipt(
        kind="managed",
        created_at=123.0,
        primary=None,
        plugins=(UpdateVersionTransition("sase-github", "1.2.0", "1.3.0"),),
        dependency_count=1,
    )


def test_build_plugin_uninstall_receipt_uses_removed_package_version() -> None:
    plan = UninstallReady(
        requirement=Requirement.from_spec("sase-github"),
        display_name="github",
        argv=["uv", "tool", "install"],
    )
    outcome = UninstallOutcome(
        plan=plan,
        change_set=UvChangeSet(
            changes=(
                UvPackageChange(
                    name="sase-github",
                    kind=ChangeKind.REMOVED,
                    old_version="1.2.0",
                ),
            )
        ),
        elapsed=0.0,
    )

    assert build_update_receipt(outcome, created_at=123.0) == UpdateToastReceipt(
        kind="managed",
        created_at=123.0,
        primary=None,
        plugins=(UpdateVersionTransition("sase-github", "1.2.0", None),),
    )


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
                diffstat=RepoDiffStat(files_changed=4, insertions=20, deletions=5),
            ),
            DevUpdateOutcome(
                record=_record("sase-github"),
                status="updated",
                reason="behind upstream by 1 commit(s)",
                old_version="0.1.0+1.gabc123def",
                new_version="0.1.0+2.gdef456abc",
                diffstat=RepoDiffStat(files_changed=1, insertions=0, deletions=0),
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
            diffstat=RepoDiffStat(files_changed=4, insertions=20, deletions=5),
        ),
        plugins=(
            UpdateVersionTransition(
                "sase-github",
                "0.1.0+1.gabc123def",
                "0.1.0+2.gdef456abc",
                diffstat=RepoDiffStat(files_changed=1, insertions=0, deletions=0),
            ),
        ),
    )


def test_build_dev_update_receipt_aggregates_hidden_plugin_diffstats() -> None:
    outcomes = [
        DevUpdateOutcome(
            record=_record("sase", role="host"),
            status="updated",
            reason="behind upstream by 1 commit(s)",
            old_version="0.5.0",
            new_version="0.6.0",
        )
    ]
    for index in range(4):
        outcomes.append(
            DevUpdateOutcome(
                record=_record(f"sase-plugin-{index}"),
                status="updated",
                reason="behind upstream by 1 commit(s)",
                old_version="0.1.0",
                new_version="0.2.0",
                diffstat=RepoDiffStat(
                    files_changed=index + 1,
                    insertions=10 + index,
                    deletions=index,
                ),
            )
        )
    result = DevUpdateResult(changed=True, outcomes=tuple(outcomes))

    receipt = build_update_receipt(result, created_at=123.0)

    assert receipt is not None
    assert len(receipt.plugins) == 3
    assert receipt.plugin_overflow == 1
    assert receipt.plugin_overflow_diffstat == RepoDiffStat(
        files_changed=4,
        insertions=13,
        deletions=3,
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
