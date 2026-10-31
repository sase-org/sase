from __future__ import annotations

import argparse
import json
from unittest.mock import patch

import pytest

from sase.agents.cli_sync import handle_agents_sync
from sase.agents_sync.models import (
    STATUS_SCHEMA_VERSION,
    ProjectSyncStatus,
    SyncOutcome,
    SyncStatusSnapshot,
)
from sase.main.parser import create_parser


def test_check_json_is_stable_and_errors_exit_nonzero(
    capsys: pytest.CaptureFixture[str],
) -> None:
    snapshot = SyncStatusSnapshot(
        10.0,
        (
            ProjectSyncStatus(
                "proj",
                "Project",
                "error",
                error="corrupt manifest",
            ),
        ),
    )
    args = argparse.Namespace(project=["proj"], check=True, refresh=False, json=True)
    with patch("sase.agents.cli_sync.get_agents_sync_status", return_value=snapshot):
        exit_code = handle_agents_sync(args)

    payload = json.loads(capsys.readouterr().out)
    assert payload["schema_version"] == STATUS_SCHEMA_VERSION
    assert payload["mode"] == "check"
    assert payload["projects"][0]["error"] == "corrupt manifest"
    assert exit_code == 1


def test_mutating_sync_json_allows_benign_skips(
    capsys: pytest.CaptureFixture[str],
) -> None:
    outcomes = (SyncOutcome("proj", "Project", skip_reason="project is disabled"),)
    args = argparse.Namespace(project=[], check=False, refresh=False, json=True)
    with patch("sase.agents.cli_sync.sync_agents", return_value=outcomes) as sync:
        exit_code = handle_agents_sync(args)

    payload = json.loads(capsys.readouterr().out)
    assert payload["mode"] == "sync"
    assert payload["projects"][0]["skip_reason"] == "project is disabled"
    assert exit_code == 0
    sync.assert_called_once_with(
        (),
        retry_quarantined=False,
        retry_retired=False,
        drop_retired=False,
        retry_limit=None,
        retry_error_classes=(),
        retry_key=None,
    )


def test_mutating_sync_forwards_drop_retired_and_renders_its_report(
    capsys: pytest.CaptureFixture[str],
) -> None:
    outcomes = (
        SyncOutcome(
            "proj",
            "Project",
            pulled=True,
            diagnostics=(
                "dropped 1 retired publication request",
                "dropped retired publication request alice.athena.lt@bbbbbbbbbbbb: "
                "hood 'lt' has no publishable runs",
            ),
        ),
    )
    args = argparse.Namespace(
        project=[],
        check=False,
        refresh=False,
        json=False,
        drop_retired=True,
    )
    with patch("sase.agents.cli_sync.sync_agents", return_value=outcomes) as sync:
        exit_code = handle_agents_sync(args)

    output = " ".join(capsys.readouterr().out.split())
    assert "dropped 1 retired publication request" in output
    assert "hood 'lt' has no publishable runs" in output
    assert exit_code == 0
    sync.assert_called_once_with(
        (),
        retry_quarantined=False,
        retry_retired=False,
        drop_retired=True,
        retry_limit=None,
        retry_error_classes=(),
        retry_key=None,
    )


def test_mutating_sync_forwards_retry_retired(
    capsys: pytest.CaptureFixture[str],
) -> None:
    outcomes = (
        SyncOutcome(
            "proj",
            "Project",
            pulled=True,
            diagnostics=("retried 1 retired publication request",),
        ),
    )
    args = argparse.Namespace(
        project=["proj"],
        check=False,
        refresh=False,
        json=False,
        retry_retired=True,
        retry_quarantined=False,
        drop_retired=False,
    )
    with patch("sase.agents.cli_sync.sync_agents", return_value=outcomes) as sync:
        exit_code = handle_agents_sync(args)

    output = " ".join(capsys.readouterr().out.split())
    assert "retried 1 retired publication request" in output
    assert exit_code == 0
    sync.assert_called_once_with(
        ("proj",),
        retry_quarantined=False,
        retry_retired=True,
        drop_retired=False,
        retry_limit=None,
        retry_error_classes=(),
        retry_key=None,
    )


def test_mutating_sync_forwards_bounded_retry_options(
    capsys: pytest.CaptureFixture[str],
) -> None:
    args = argparse.Namespace(
        project=["proj"],
        check=False,
        refresh=False,
        json=True,
        retry_retired=False,
        retry_quarantined=True,
        drop_retired=False,
        retry_limit=3,
        retry_error_class=["timeout", "lock_busy"],
    )
    with patch("sase.agents.cli_sync.sync_agents", return_value=()) as sync:
        assert handle_agents_sync(args) == 0

    assert json.loads(capsys.readouterr().out)["mode"] == "sync"
    sync.assert_called_once_with(
        ("proj",),
        retry_quarantined=True,
        retry_retired=False,
        drop_retired=False,
        retry_limit=3,
        retry_error_classes=("timeout", "lock_busy"),
        retry_key=None,
    )


def test_mutating_sync_forwards_retry_key(
    capsys: pytest.CaptureFixture[str],
) -> None:
    identity = ("alice.athena.worker", "c" * 40)
    args = argparse.Namespace(
        project=["proj"],
        check=False,
        refresh=False,
        json=True,
        retry_retired=False,
        retry_quarantined=True,
        drop_retired=False,
        retry_limit=1,
        retry_error_class=["timeout"],
        retry_key=identity,
    )
    with patch("sase.agents.cli_sync.sync_agents", return_value=()) as sync:
        assert handle_agents_sync(args) == 0

    assert json.loads(capsys.readouterr().out)["mode"] == "sync"
    sync.assert_called_once_with(
        ("proj",),
        retry_quarantined=True,
        retry_retired=False,
        drop_retired=False,
        retry_limit=1,
        retry_error_classes=("timeout",),
        retry_key=identity,
    )


def test_mutating_sync_pretty_table_reports_counts_and_result(
    capsys: pytest.CaptureFixture[str],
) -> None:
    outcomes = (
        SyncOutcome(
            "proj",
            "Project",
            pulled=True,
            exported=2,
            committed=True,
            pushed=True,
        ),
    )
    args = argparse.Namespace(project=[], check=False, refresh=False, json=False)
    with patch("sase.agents.cli_sync.sync_agents", return_value=outcomes):
        exit_code = handle_agents_sync(args)

    output = capsys.readouterr().out
    assert "Agent Sync" in output
    assert "Project" in output
    assert "synchronized" in output
    assert exit_code == 0


def test_repair_digests_dispatches_before_check_and_reports_diagnostics(
    capsys: pytest.CaptureFixture[str],
) -> None:
    outcomes = (
        SyncOutcome(
            "proj",
            "Project",
            committed=True,
            pushed=True,
            diagnostics=("foo: agents/alice.athena.foo/chat.md",),
        ),
    )
    args = argparse.Namespace(
        project=["proj"],
        check=False,
        refresh=False,
        json=True,
        repair_digests=True,
    )
    with patch(
        "sase.agents.cli_sync.repair_agent_hood_digests", return_value=outcomes
    ) as repair:
        exit_code = handle_agents_sync(args)

    payload = json.loads(capsys.readouterr().out)
    assert payload["mode"] == "repair-digests"
    assert payload["projects"][0]["diagnostics"] == [
        "foo: agents/alice.athena.foo/chat.md"
    ]
    assert exit_code == 0
    repair.assert_called_once_with(("proj",))


def test_repair_manifest_dispatches_before_check_and_reports_diagnostics(
    capsys: pytest.CaptureFixture[str],
) -> None:
    outcomes = (
        SyncOutcome(
            "proj",
            "Project",
            committed=True,
            pushed=True,
            diagnostics=("foo: recovered",),
        ),
    )
    args = argparse.Namespace(
        project=["proj"],
        check=False,
        refresh=False,
        json=True,
        repair_digests=False,
        repair_manifest=True,
    )
    with patch(
        "sase.agents.cli_sync.repair_agent_owner_manifests", return_value=outcomes
    ) as repair:
        exit_code = handle_agents_sync(args)

    payload = json.loads(capsys.readouterr().out)
    assert payload["mode"] == "repair-manifest"
    assert payload["projects"][0]["diagnostics"] == ["foo: recovered"]
    assert exit_code == 0
    repair.assert_called_once_with(("proj",))
