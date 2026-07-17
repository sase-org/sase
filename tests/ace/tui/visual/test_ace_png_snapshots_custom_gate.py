"""PNG snapshots for the generic custom notification-gate modal."""

from __future__ import annotations

import pytest

from sase.ace.testing import AcePage
from sase.ace.tui.modals.custom_gate_modal import (
    CustomGateModal,
    CustomGateModalData,
)
from sase.notification_gates.models import GateChoice
from tests.ace.tui.visual._ace_png_snapshot_helpers import (
    changespecs,
    patch_startup_loaders,
    wait_for_startup,
    wait_for_visual_idle,
)
from tests.ace.tui.visual.png_diff import AcePngSnapshotFixture

pytestmark = pytest.mark.visual


def _choice(
    choice_id: str,
    label: str,
    *,
    icon: str,
    feedback: str = "disabled",
    extras: list[dict[str, object]] | None = None,
) -> GateChoice:
    return GateChoice.from_mapping(
        {
            "id": choice_id,
            "label": label,
            "icon": icon,
            "feedback": feedback,
            "command": {"argv": [f"commands/{choice_id}"]},
            "extras": extras or [],
        },
        0,
        default_feedback="optional",
    )


def _data(*choices: GateChoice) -> CustomGateModalData:
    return CustomGateModalData(
        request_id="deploy-production-42",
        sender="release-guardian",
        icon="🛡️",
        notes=(
            "The release agent is ready to deploy the signed build.",
            "Choose one outcome and optionally add follow-up commands.",
        ),
        attachments=("release-preview.md", "deployment-manifest.json"),
        preview_name="release-preview.md",
        preview_text=(
            "# Production deployment\n\n"
            "- Version: `0.10.2`\n"
            "- Region: `us-east-1`\n"
            "- Health checks: passing\n"
        ),
        choices=choices,
    )


async def _snapshot_modal(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
    *,
    data: CustomGateModalData,
    snapshot_name: str,
    title: str,
) -> None:
    patch_startup_loaders(monkeypatch, agents=[])
    async with AcePage(
        query='"visual"',
        size=(120, 40),
        changespecs=changespecs(),
    ) as page:
        await wait_for_startup(page)
        page.app.push_screen(CustomGateModal(data))
        await page.expect_modal("CustomGateModal")
        await wait_for_visual_idle(page)
        ace_png_visual.assert_page_png(page, snapshot_name, title=title)


async def test_custom_gate_choices_only_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await _snapshot_modal(
        ace_png_visual,
        monkeypatch,
        data=_data(
            _choice("approve", "Approve deployment", icon="✅"),
            _choice("cancel", "Cancel release", icon="🛑"),
        ),
        snapshot_name="custom_gate_choices_only_120x40",
        title="ACE custom gate choices",
    )


async def test_custom_gate_extras_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await _snapshot_modal(
        ace_png_visual,
        monkeypatch,
        data=_data(
            _choice(
                "deploy",
                "Deploy signed build",
                icon="🚀",
                feedback="optional",
                extras=[
                    {
                        "id": "announce",
                        "label": "Post release announcement",
                        "icon": "📣",
                        "default_selected": True,
                        "command": {"argv": ["commands/announce"]},
                    },
                    {
                        "id": "monitor",
                        "label": "Start ten-minute health monitor",
                        "icon": "📈",
                        "default_selected": True,
                        "command": {"argv": ["commands/monitor"]},
                    },
                    {
                        "id": "cleanup",
                        "label": "Remove staging artifacts",
                        "icon": "🧹",
                        "command": {"argv": ["commands/cleanup"]},
                    },
                ],
            ),
            _choice("cancel", "Cancel release", icon="🛑"),
        ),
        snapshot_name="custom_gate_extras_120x40",
        title="ACE custom gate extras",
    )


async def test_custom_gate_required_feedback_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await _snapshot_modal(
        ace_png_visual,
        monkeypatch,
        data=_data(
            _choice(
                "override",
                "Override warning",
                icon="⚠️",
                feedback="required",
            ),
            _choice("cancel", "Cancel release", icon="🛑"),
        ),
        snapshot_name="custom_gate_required_feedback_120x40",
        title="ACE custom gate required feedback",
    )
