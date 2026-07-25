"""PNG snapshots for the Gate Debug modal."""

from __future__ import annotations

from pathlib import Path

import pytest

from sase.ace.testing import AcePage
from sase.ace.tui.modals.gate_debug_modal import GateDebugModal
from sase.notification_gates.debug import (
    GateDebugArtifact,
    GateDebugContext,
    _GateDebugError,
    _GateDebugResource,
    GateDebugSnapshot,
)
from sase.notifications.models import Notification
from tests.ace.tui.visual._ace_png_snapshot_helpers import (
    changespecs,
    patch_startup_loaders,
    wait_for_startup,
    wait_for_visual_idle,
)
from tests.ace.tui.visual.png_diff import AcePngSnapshotFixture

pytestmark = pytest.mark.visual

_BUNDLE = Path("/home/operator/.sase/interaction_requests/custom/deploy-production-42")


def _context() -> GateDebugContext:
    notification = Notification(
        id="8ad8d3ce-45a2-4e24-9602-fadf703ee1ca",
        timestamp="2026-07-17T13:30:00+00:00",
        sender="release-guardian",
        icon="🛡️",
        notes=["Production deployment review"],
        tags=["release", "production"],
        action="CustomGate",
        action_data={
            "request_id": "deploy-production-42",
            "request_kind": "custom",
            "bundle_path": str(_BUNDLE),
        },
    )
    return GateDebugContext(notification, notification.action_data)


def _snapshot(*, answered: bool) -> GateDebugSnapshot:
    request_text = """{
  "schema_version": 2,
  "request_id": "deploy-production-42",
  "kind": "custom",
  "query": "(deploy AND announce AND monitor) OR cancel",
  "branches": [["deploy", "announce", "monitor"], ["cancel"]],
  "continuation_mode": "resume_agent"
}"""
    response_text = """{
  "schema_version": 2,
  "request_id": "deploy-production-42",
  "kind": "custom",
  "selected_option_ids": [
    "deploy",
    "announce",
    "monitor"
  ],
  "feedback": "Release checks passed.",
  "option_results": [
    {"id": "deploy", "result": {"deployed": true}},
    {"id": "announce", "result": {"announced": true}}
  ]
}"""
    error_body = (
        "✗ 1721224810-monitor.json\n"
        "  code: command_failed\n"
        "  message: health monitor exited during startup\n"
        "  source: ace\n"
        "  returncode: 7\n"
        "  stderr:\n"
        "    monitor endpoint refused connection"
    )
    overview = """Status              PENDING
Kind                custom
Request id          deploy-production-42
Notification id     8ad8d3ce-45a2-4e24-9602-fadf703ee1ca
Sender / producer   release-guardian @ athena
Continuation        resume_agent
Bundle              /home/operator/.sase/interaction_requests/custom/deploy-production-42
Created             2026-07-17T09:30:00-04:00
Age                 12m ago
Timeout             30m
Deadline state      18m remaining
Status detail       waiting for a terminal response

Branches
  🚀 deploy AND 📣 announce AND 📈 monitor | submit=🚀 Deploy signed build
  🛑 cancel

Options
  🚀 deploy: Deploy signed build | feedback=optional | argv=commands/deploy
  📣 announce: Post release announcement | feedback=disabled | argv=commands/announce
  📈 monitor: Start health monitor | feedback=disabled | argv=commands/monitor
  🛑 cancel: Cancel release | feedback=disabled | argv=commands/cancel

Resource integrity
  state  size       mode  role        path
  ✓      1.4 KiB    exec  command     commands/deploy
  ✓      862 B      file  preview     release-preview.md
  ⚠      —          file  attachment  deployment-manifest.json
         resource is missing

Notification / pending action
Read                false
Dismissed           false
Muted               false
Tags                release, production
Pending action      available; transports notification_store, telegram"""
    error = _GateDebugError(
        path=_BUNDLE / "errors" / "1721224810-monitor.json",
        code="command_failed",
        message="health monitor exited during startup",
        source="ace",
        returncode=7,
        stdout=None,
        stderr="monitor endpoint refused connection",
        body=error_body,
    )
    return GateDebugSnapshot(
        kind="custom",
        request_id="deploy-production-42",
        notification_id="8ad8d3ce-45a2-4e24-9602-fadf703ee1ca",
        icon="🛡️",
        status="ANSWERED" if answered else "PENDING",
        created_at="2026-07-17T09:30:00-04:00",
        age="12m ago",
        bundle_path=_BUNDLE,
        overview=GateDebugArtifact("ok", overview, overview, path=_BUNDLE),
        request=GateDebugArtifact(
            "ok", request_text, request_text, path=_BUNDLE / "request.json"
        ),
        response=GateDebugArtifact(
            "ok" if answered else "missing",
            response_text
            if answered
            else "Pending — no response has been written yet.",
            response_text
            if answered
            else "Pending — no response has been written yet.",
            path=_BUNDLE / "response.json",
        ),
        errors=(error,) if answered else (),
        error_count=1 if answered else 0,
        errors_artifact=GateDebugArtifact(
            "ok" if answered else "missing",
            error_body if answered else "No gate execution errors recorded.",
            error_body if answered else "No gate execution errors recorded.",
            path=_BUNDLE / "errors",
        ),
        row=GateDebugArtifact(
            "ok",
            '{"id": "8ad8d3ce-45a2-4e24-9602-fadf703ee1ca"}',
            '{"id": "8ad8d3ce-45a2-4e24-9602-fadf703ee1ca"}',
        ),
        resources=(
            _GateDebugResource(
                "commands/deploy", "command", True, 1433, "ok", "sha256 abc"
            ),
            _GateDebugResource(
                "release-preview.md", "preview", False, 862, "ok", "sha256 def"
            ),
            _GateDebugResource(
                "deployment-manifest.json",
                "attachment",
                False,
                None,
                "missing",
                "resource is missing",
            ),
        ),
    )


async def _snapshot_modal(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
    *,
    snapshot: GateDebugSnapshot,
    tab_index: int,
    snapshot_name: str,
    title: str,
) -> None:
    patch_startup_loaders(monkeypatch, agents=[])
    monkeypatch.setattr(
        "sase.ace.tui.modals.gate_debug_modal.build_gate_debug_snapshot",
        lambda *_args, **_kwargs: snapshot,
    )
    async with AcePage(
        query='"visual"',
        size=(120, 40),
        changespecs=changespecs(),
    ) as page:
        await wait_for_startup(page)
        await page.press("5")
        await page.expect_state("artifacts_subtab", "prs")
        modal = GateDebugModal(_context())
        page.app.push_screen(modal)
        await page.expect_modal("GateDebugModal")
        for _ in range(10):
            await page.pause()
            if modal._snapshot is not None:
                break
        for _ in range(tab_index):
            await page.press("]")
            await page.pause()
        await wait_for_visual_idle(page)
        ace_png_visual.assert_page_png(page, snapshot_name, title=title)


async def test_gate_debug_pending_overview_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await _snapshot_modal(
        ace_png_visual,
        monkeypatch,
        snapshot=_snapshot(answered=False),
        tab_index=0,
        snapshot_name="gate_debug_pending_overview_120x40",
        title="ACE Gate Debug pending overview",
    )


async def test_gate_debug_answered_response_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await _snapshot_modal(
        ace_png_visual,
        monkeypatch,
        snapshot=_snapshot(answered=True),
        tab_index=2,
        snapshot_name="gate_debug_answered_response_120x40",
        title="ACE Gate Debug answered response",
    )
