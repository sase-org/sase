"""Temporary probe v2: count bead-touch loader calls + dump SVG late (deleted after use)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from sase.ace.testing import AcePage
from tests.ace.tui.visual._ace_agents_png_snapshot_helpers import page_svg_text
from tests.ace.tui.visual._ace_png_snapshot_helpers import (
    patches,
    patch_startup_loaders,
    wait_for_startup,
)
from tests.ace.tui.visual.test_ace_png_snapshots_agents_sase_context_beads import (
    _created_bead_agent,
    _created_bead_touches,
)

pytestmark = pytest.mark.visual


async def test_probe_touch_loader_calls(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    agent = _created_bead_agent(tmp_path, phase_bead_id=None)
    touches = _created_bead_touches()
    calls: list[str] = []

    def fake_loader(_agent: object) -> tuple[object, ...]:
        calls.append(getattr(_agent, "cl_name", "?") or "?")
        return touches  # type: ignore[return-value]

    monkeypatch.setattr(
        "sase.ace.tui.bead_touches.load_bead_touches_for_agent_context",
        fake_loader,
    )
    patch_startup_loaders(monkeypatch, agents=[agent])
    async with AcePage(query='"visual"', patches=patches(), size=(90, 32)) as page:
        await wait_for_startup(page)
        await page.press("shift+tab")
        await page.expect_state("tab", "agents")
        await page.expect_state("agent_count", 1)
        await page.pause(20)
        Path("/tmp/svg_late.txt").write_text(page_svg_text(page))
        Path("/tmp/loader_calls.json").write_text(json.dumps(calls))
