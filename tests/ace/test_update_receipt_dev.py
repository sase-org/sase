"""Tests for constructing development update receipts."""

from __future__ import annotations

from sase.ace.update_receipt import (
    RepoCommitGroup,
    UpdateToastReceipt,
    UpdateVersionTransition,
    build_update_receipt,
)
from sase.dev_update.models import (
    DevUpdateOutcome,
    DevUpdateResult,
    RepoCommit,
    RepoCommitLog,
    RepoDiffStat,
)
from sase.main.update_types import CombinedUpdateResult
from sase.uv_tool.render import UpdateSummary
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


def test_build_combined_receipt_carries_dev_commit_groups() -> None:
    result = CombinedUpdateResult(
        dev_result=DevUpdateResult(
            changed=True,
            outcomes=(
                DevUpdateOutcome(
                    record=_record("sase", role="host"),
                    status="updated",
                    reason="behind upstream by 1 commit(s)",
                    old_version="0.5.0",
                    new_version="0.6.0",
                    git_root="/repo/sase",
                    commits=RepoCommitLog(
                        total=1,
                        commits=(RepoCommit("abc1234", "feat: applied commits"),),
                    ),
                ),
            ),
        ),
        managed_summary=UpdateSummary(outcomes=()),
        elapsed=0.2,
    )

    receipt = build_update_receipt(result, created_at=123.0)

    assert receipt is not None
    assert receipt.commit_groups == (
        RepoCommitGroup(
            label="sase",
            commits=RepoCommitLog(
                total=1,
                commits=(RepoCommit("abc1234", "feat: applied commits"),),
            ),
        ),
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


def test_build_dev_receipt_orders_dedupes_and_caps_commit_groups() -> None:
    def outcome(
        name: str,
        role: str,
        git_root: str,
        short_sha: str,
    ) -> DevUpdateOutcome:
        return DevUpdateOutcome(
            record=_record(name, role=role),
            status="updated",
            reason="behind upstream by 1 commit(s)",
            old_version="0.1.0",
            new_version="0.2.0",
            git_root=git_root,
            commits=RepoCommitLog(
                total=1,
                commits=(RepoCommit(short_sha, f"update {name}"),),
            ),
        )

    result = DevUpdateResult(
        changed=True,
        outcomes=(
            outcome("sase-helper", "host", "/repo/rest", "0000001"),
            outcome("sase-plugin-a", "plugin", "/repo/a", "aaaaaaa"),
            outcome("sase-plugin-a-shadow", "plugin", "/repo/a", "aaaaaaa"),
            outcome("sase-core-rs", "core", "/repo/core", "ccccccc"),
            outcome("sase", "host", "/repo/sase", "sssssss"),
            outcome("sase-plugin-b", "plugin", "/repo/b", "bbbbbbb"),
            outcome("sase-plugin-c", "plugin", "/repo/c", "ddddddd"),
        ),
    )

    receipt = build_update_receipt(result, created_at=123.0)

    assert receipt is not None
    assert [group.label for group in receipt.commit_groups] == [
        "sase",
        "sase-core-rs",
        "sase-plugin-a",
        "sase-plugin-b",
        "sase-plugin-c",
    ]
    assert receipt.commit_group_overflow == 1


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
