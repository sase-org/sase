"""End-to-end preview, quarantine, notification, and restore proof."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from textual.app import App, ComposeResult
from textual.widgets import Static

from sase.ace.testing.wait import wait_for
from sase.ace.tui.actions.agents._notification_dispatch import open_notification_action
from sase.ace.tui.modals.artifact_run_prune_modal import ArtifactRunPruneModal
from sase.ace.tui.modals.notification_modal import NotificationModal
from sase.artifact_cli.prune_runs import handle_prune_runs
from sase.artifact_cli.trash import handle_trash
from sase.chops.builtin import run_builtin_chop
from sase.core.agent_artifact_index_lifecycle_mutations import (
    upsert_agent_artifact_index_artifacts,
)
from sase.core.agent_artifact_run_retention_models import AceRunProtectionSnapshot
from sase.core.agent_scan_facade import (
    default_agent_artifact_index_path,
    load_agent_artifact_index_projection,
)
from sase.main.parser import create_parser
from sase.notifications.store import load_notifications
from sase.project_display_names import ProjectRefDisplaySnapshot
from tests._axe_chop_output_contract_helpers import (
    _isolate_chop_result_file,  # noqa: F401 (registers the isolation fixture)
    _write_context,
)


class _PruneFlowApp(App[None]):
    ENABLE_COMMAND_PALETTE = False

    def __init__(self, notification: Any) -> None:
        super().__init__()
        self.notification = notification
        self.dispatched = False
        self.notifications: list[tuple[str, str]] = []
        self.submissions: list[tuple[list[str], dict[str, Any]]] = []
        self._proc_projection: object | None = None

    def compose(self) -> ComposeResult:
        yield Static("prune flow test")

    def on_mount(self) -> None:
        self.push_screen(
            NotificationModal([self.notification]), self._on_notification_selected
        )

    def _on_notification_selected(self, notification: Any) -> None:
        if notification is not None:
            self.dispatched = open_notification_action(self, notification)

    def _submit_durable_proc(self, argv: list[str], **kwargs: Any) -> object:
        self.submissions.append((argv, kwargs))
        return object()

    def notify(self, message: str, *, severity: str = "information") -> None:
        self.notifications.append((message, severity))


def _terminal_run(projects_root: Path, timestamp: str, content: bytes) -> Path:
    path = (
        projects_root
        / "fixture-project"
        / "artifacts"
        / "ace-run"
        / timestamp[:6]
        / timestamp[6:8]
        / timestamp
    )
    path.mkdir(parents=True)
    (path / "done.json").write_text('{"outcome":"completed"}', encoding="utf-8")
    (path / "payload.bin").write_bytes(content)
    return path


def _indexed_dirs() -> set[str]:
    projection = load_agent_artifact_index_projection(
        default_agent_artifact_index_path(), ("artifact_dir",)
    )
    return {str(row[0]) for row in projection.get("rows", ())}


async def _wait_until_ready(pilot: Any, modal: ArtifactRunPruneModal) -> None:
    await wait_for(pilot, lambda: modal._view.state != "CHECKING")


async def test_preview_dispatch_quarantine_and_restore_round_trip(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    home = tmp_path / "sase-home"
    projects_root = home / "projects"
    monkeypatch.setenv("SASE_HOME", str(home))
    eligible = _terminal_run(projects_root, "20200101000000", b"eligible run\x00\x01\n")
    referenced = _terminal_run(
        projects_root, "20200202000000", b"referenced run\x02\x03\n"
    )
    eligible_bytes = {
        path.relative_to(eligible): path.read_bytes()
        for path in eligible.rglob("*")
        if path.is_file()
    }
    protections = AceRunProtectionSnapshot(
        protected_dirs=frozenset({str(referenced.resolve())}),
        sources_scanned=("fixture reference",),
    )

    import importlib

    chop = importlib.import_module("sase.scripts.sase_chop_artifact_run_prune")
    publish = importlib.import_module("sase.core.agent_artifact_run_prune_publish")
    prune_cli = importlib.import_module("sase.artifact_cli.prune_runs")
    trash_cli = importlib.import_module("sase.artifact_cli.trash")
    monkeypatch.setattr(
        chop,
        "collect_ace_run_retention_protections",
        lambda **_kwargs: protections,
    )
    monkeypatch.setattr(
        publish,
        "load_project_ref_display_snapshot",
        lambda **_kwargs: ProjectRefDisplaySnapshot(),
    )
    monkeypatch.setattr(
        prune_cli,
        "collect_ace_run_retention_protections",
        lambda **_kwargs: protections,
    )
    monkeypatch.setattr(
        trash_cli,
        "collect_ace_run_retention_protections",
        lambda **_kwargs: protections,
    )
    monkeypatch.setattr(
        chop,
        "purge_ace_run_trash",
        lambda *_args, **_kwargs: SimpleNamespace(
            purged=0,
            restored=0,
            freed_bytes=0,
            blocked_reason=None,
            errors=0,
            index_errors=(),
        ),
    )

    assert upsert_agent_artifact_index_artifacts([eligible, referenced]) == 2
    initial_index = _indexed_dirs()
    assert {str(eligible), str(referenced)} <= initial_index

    context_path = _write_context(tmp_path, tmp_path / "chop-result.json")
    run_builtin_chop("artifact_run_prune", ["--context", str(context_path)])
    capsys.readouterr()
    preview_rows = [
        row
        for row in load_notifications(include_dismissed=True)
        if (row.dedup_key or "").startswith("artifact_run_prune:")
    ]
    assert len(preview_rows) == 1
    preview = preview_rows[0]
    assert preview.action_data["run_prune_review"]

    app = _PruneFlowApp(preview)
    async with app.run_test(size=(120, 40)) as pilot:
        assert isinstance(app.screen, NotificationModal)
        await pilot.press("enter")
        assert isinstance(app.screen, ArtifactRunPruneModal)
        modal = app.screen
        await _wait_until_ready(pilot, modal)
        assert modal._view.state == "READY"
        await pilot.press("y")
        assert len(app.submissions) == 1

    argv, submission = app.submissions[0]
    assert app.dispatched is True
    assert submission["operation"] == "artifact.prune-runs"
    review_payload = json.loads(preview.action_data["run_prune_review"])
    assert argv[1:] == [
        "artifact",
        "prune-runs",
        "--apply",
        "--snapshot",
        review_payload["fingerprint"],
        "--notify",
        "--json",
    ]
    apply_args = create_parser().parse_args(argv[1:])
    assert handle_prune_runs(apply_args) == 0
    apply_result = json.loads(capsys.readouterr().out)
    assert apply_result["execution"]["quarantined"] == 1
    batch_id = apply_result["execution"]["batch_id"]
    assert batch_id
    assert not eligible.exists()
    assert referenced.exists()

    after_quarantine = _indexed_dirs()
    assert str(eligible) not in after_quarantine
    assert str(referenced) in after_quarantine
    rows = {row.dedup_key: row for row in load_notifications(include_dismissed=True)}
    preview_after_apply = rows[preview.dedup_key]
    assert preview_after_apply.dismissed is True
    result_row = rows[f"artifact_run_trash:{batch_id}"]
    assert result_row.dismissed is False

    restore_args = create_parser().parse_args(
        ["artifact", "trash", "restore", f"runs:{batch_id}", "--json"]
    )
    assert handle_trash(restore_args) == 0
    restore_result = json.loads(capsys.readouterr().out)
    assert restore_result["restored"] == 1
    assert eligible.exists()
    assert {
        path.relative_to(eligible): path.read_bytes()
        for path in eligible.rglob("*")
        if path.is_file()
    } == eligible_bytes
    assert _indexed_dirs() >= initial_index
    assert str(eligible) in _indexed_dirs()
