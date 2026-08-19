"""PNG snapshots for the ACE gate input panel."""

from __future__ import annotations

import pytest

from sase.ace.testing import AcePage
from sase.ace.tui.modals.gate_input_panel import GateInputPanel
from sase.ace.tui.modals.gate_input_panel_model import build_gate_input_request
from sase.notification_gates.models import GateOption
from tests.ace.tui.visual._ace_png_snapshot_helpers import (
    patches,
    patch_startup_loaders,
    wait_for_startup,
    wait_for_svg_contains,
    wait_for_visual_idle,
)
from tests.ace.tui.visual.png_diff import AcePngSnapshotFixture

pytestmark = pytest.mark.visual


def _panel_option(
    option_id: str,
    label: str,
    *,
    icon: str,
    inputs: list[dict[str, object]] | None = None,
    input_schema: dict[str, object] | None = None,
    feedback: str = "disabled",
) -> GateOption:
    payload: dict[str, object] = {
        "id": option_id,
        "label": label,
        "icon": icon,
        "feedback": feedback,
        "command": {"argv": [f"commands/{option_id}"]},
    }
    if inputs is not None:
        payload["inputs"] = inputs
    if input_schema is not None:
        payload["input_schema"] = input_schema
    return GateOption.from_mapping(payload, 0)


async def _snapshot_panel(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
    *,
    panel: GateInputPanel,
    snapshot_name: str,
    title: str,
    sentinel: str,
    size: tuple[int, int] = (120, 45),
) -> None:
    patch_startup_loaders(monkeypatch, agents=[])
    async with AcePage(
        query='"visual"',
        size=size,
        patches=patches(),
    ) as page:
        await wait_for_startup(page)
        await page.press("2")
        await page.expect_state("artifacts_subtab", "patches")
        page.app.push_screen(panel)
        await page.expect_modal("GateInputPanel")
        await wait_for_svg_contains(page, sentinel)
        await wait_for_visual_idle(page)
        ace_png_visual.assert_page_png(page, snapshot_name, title=title)


async def test_gate_input_panel_single_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    option = _panel_option(
        "deploy",
        "Deploy signed build",
        icon="🚀",
        feedback="optional",
        inputs=[
            {
                "id": "target_env",
                "label": "Target environment",
                "type": "line",
                "required": True,
            },
            {
                "id": "mode",
                "label": "Mode",
                "type": "enum",
                "choices": ["fast", "thorough"],
            },
            {
                "id": "token",
                "label": "Access token",
                "type": "line",
                "secret": True,
            },
        ],
    )
    request = build_gate_input_request(
        (option,),
        ("deploy",),
        branch_index=0,
        branch_label="Deploy signed build",
        feedback_mode="optional",
    )
    await _snapshot_panel(
        ace_png_visual,
        monkeypatch,
        panel=GateInputPanel(
            request,
            headline="Approve production deployment",
            kind="custom",
            request_id="deploy-production-42",
        ),
        snapshot_name="gate_input_panel_single_120x45",
        title="ACE gate input panel single option",
        sentinel="Target environment",
    )


async def test_gate_input_panel_group_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    deploy = _panel_option(
        "deploy",
        "Deploy signed build",
        icon="🚀",
        inputs=[
            {
                "id": "target",
                "label": "Target environment",
                "type": "line",
                "required": True,
            },
            {
                "id": "mode",
                "label": "Mode",
                "type": "enum",
                "choices": ["fast", "thorough"],
            },
        ],
    )
    announce = _panel_option(
        "announce",
        "Post release announcement",
        icon="📣",
        inputs=[
            {
                "id": "target",
                "label": "Target environment",
                "type": "line",
                "required": True,
            }
        ],
    )
    rotate = _panel_option(
        "rotate",
        "Rotate deploy credentials",
        icon="🔑",
        input_schema={
            "type": "object",
            "properties": {
                "reason": {"type": "string", "default": "quarterly rotation"},
            },
            "required": ["reason"],
        },
    )
    request = build_gate_input_request(
        (deploy, announce, rotate),
        ("deploy", "announce", "rotate"),
        branch_index=0,
        branch_label="Ship the release",
    )
    await _snapshot_panel(
        ace_png_visual,
        monkeypatch,
        panel=GateInputPanel(
            request,
            headline="Approve production deployment",
            kind="custom",
            request_id="deploy-production-42",
        ),
        snapshot_name="gate_input_panel_group_120x45",
        title="ACE gate input panel AND group",
        sentinel="also sent to",
    )


async def test_gate_input_panel_note_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    option = _panel_option(
        "override",
        "Override warning",
        icon="⚠️",
        feedback="required",
    )
    request = build_gate_input_request(
        (option,),
        ("override",),
        branch_index=0,
        branch_label="Override warning",
        feedback_mode="required",
    )
    await _snapshot_panel(
        ace_png_visual,
        monkeypatch,
        panel=GateInputPanel(
            request,
            headline="Approve production deployment",
            kind="custom",
            request_id="deploy-production-42",
        ),
        snapshot_name="gate_input_panel_note_120x40",
        title="ACE gate input panel required note",
        sentinel="Note",
        size=(120, 40),
    )
