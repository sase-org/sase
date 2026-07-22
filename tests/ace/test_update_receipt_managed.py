"""Tests for constructing managed and plugin update receipts."""

from __future__ import annotations

from sase.ace.update_receipt import (
    UpdateToastReceipt,
    UpdateVersionTransition,
    build_update_receipt,
)
from sase.dev_update.models import DevUpdateResult
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
from sase.uv_tool.receipt import Requirement
from sase.uv_tool.render import UpdateOutcome, UpdateSummary
from sase.uv_tool.runner import ChangeKind, UvChangeSet, UvPackageChange


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
