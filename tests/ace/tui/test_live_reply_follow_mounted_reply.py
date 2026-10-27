"""Mounted single-agent Muse parser-to-Reply-card streaming coverage."""

from __future__ import annotations

import asyncio
import re
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any

import pytest

from sase.ace.testing import AcePage
from sase.ace.tui.models.agent import Agent, AgentType
from sase.ace.tui.widgets.prompt_panel import AgentPromptPanel
from sase.llm_provider._subprocess import stream_and_parse_muse_json_output
from tests.ace.tui._live_reply_follow_mounted_helpers import (
    MOUNTED_ANSWER,
    MOUNTED_COMMENTARY_1,
    MOUNTED_COMMENTARY_2,
    MOUNTED_MUSE_SESSION_ID,
    gated_muse_script,
    reply_card_text,
    wait_for_page,
)
from tests.ace.tui.visual._ace_png_snapshot_helpers import (
    patch_startup_loaders,
    patches,
    wait_for_startup,
    wait_for_visual_idle,
)


def _agent(artifacts_dir: Path) -> Agent:
    return Agent(
        agent_type=AgentType.RUNNING,
        cl_name="muse-stream-mounted",
        project_file="/tmp/muse-stream-mounted.sase",
        status="RUNNING",
        start_time=datetime(2026, 10, 3, 12, 0, 0),
        raw_suffix="20261003120000-mounted",
        agent_name="muse-stream-mounted",
        llm_provider="muse",
        model="muse-spark-1.2",
        artifacts_dir=str(artifacts_dir),
    )


@pytest.mark.asyncio
async def test_gated_muse_stream_reaches_mounted_reply_before_terminal(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    artifacts_dir = tmp_path / "muse-stream-artifacts"
    artifacts_dir.mkdir()
    (artifacts_dir / "raw_prompt.md").write_text(
        "Run the mounted Muse stream fixture.\n", encoding="utf-8"
    )
    (artifacts_dir / "01_prompt.md").write_text(
        "Wait for the gated provider reply.\n", encoding="utf-8"
    )
    reply_path = artifacts_dir / "live_reply.md"
    timestamps_path = artifacts_dir / "live_reply_timestamps.jsonl"
    reply_path.write_text("", encoding="utf-8")
    timestamps_path.write_text("", encoding="utf-8")
    monkeypatch.setenv("SASE_ARTIFACTS_DIR", str(artifacts_dir))
    agent = _agent(artifacts_dir)
    patch_startup_loaders(monkeypatch, agents=[agent])

    async with AcePage(
        query='"muse-stream-mounted"',
        patches=patches(),
    ) as page:
        await wait_for_startup(page)
        await page.press("shift+tab")
        await page.expect_state("tab", "agents")
        await page.expect_state("agent_count", 1)
        await wait_for_visual_idle(page)
        await page.press("j")
        await wait_for_visual_idle(page)
        panel = page.query_one_widget("#agent-prompt-panel", AgentPromptPanel)
        await wait_for_page(
            page,
            lambda: panel._live_reply_source is not None,
            "selected live reply source setup",
        )
        route_calls: list[tuple[Path, ...]] = []
        on_live_reply_artifact_change = panel.on_live_reply_artifact_change

        def track_live_reply_route(paths: tuple[Path, ...]) -> None:
            route_calls.append(paths)
            on_live_reply_artifact_change(paths)

        monkeypatch.setattr(
            panel, "on_live_reply_artifact_change", track_live_reply_route
        )
        await page.press("ctrl+j")
        await wait_for_visual_idle(page)

        refresh_calls: list[tuple[tuple[Any, ...], dict[str, Any]]] = []
        schedule_refresh = page.app._schedule_agents_async_refresh

        def track_refresh(*args: Any, **kwargs: Any) -> Any:
            refresh_calls.append((args, kwargs))
            return schedule_refresh(*args, **kwargs)

        monkeypatch.setattr(page.app, "_schedule_agents_async_refresh", track_refresh)

        # The session-log tail resolves its log through XDG_DATA_HOME in this
        # same process, so point it at a per-test fake home the fixture populates.
        xdg_home = tmp_path / "xdg-home"
        xdg_home.mkdir(exist_ok=True)
        monkeypatch.setenv("XDG_DATA_HOME", str(xdg_home))

        first_sent = tmp_path / "first-sent"
        release_second = tmp_path / "release-second"
        second_sent = tmp_path / "second-sent"
        release_terminal = tmp_path / "release-terminal"
        terminal_sent = tmp_path / "terminal-sent"
        process = subprocess.Popen(
            [
                sys.executable,
                "-u",
                "-c",
                gated_muse_script(),
                str(first_sent),
                str(release_second),
                str(second_sent),
                str(release_terminal),
                str(terminal_sent),
            ],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        parser_task = asyncio.create_task(
            asyncio.to_thread(
                stream_and_parse_muse_json_output,
                process,
                suppress_output=True,
                session_id=MOUNTED_MUSE_SESSION_ID,
            )
        )
        try:
            await wait_for_page(page, first_sent.exists, "first commentary record")
            await wait_for_page(
                page,
                lambda: reply_path.read_text(encoding="utf-8").startswith(
                    MOUNTED_COMMENTARY_1
                ),
                "tail to append the first commentary chunk",
            )
            assert process.poll() is None
            assert not terminal_sent.exists()
            assert not (artifacts_dir / "done.json").exists()

            # Exercise the actual artifact watcher route while the fake provider is
            # blocked before its terminal record.
            await wait_for_page(
                page,
                lambda: not page.app._nav_gate.is_navigating(),
                "navigation settles before the watcher route",
            )
            page.app._on_artifact_change((reply_path, timestamps_path))
            assert len(route_calls) == 1
            await wait_for_page(
                page,
                lambda: MOUNTED_COMMENTARY_1 in reply_card_text(page),
                "first commentary in the mounted Reply card",
            )
            assert process.poll() is None
            assert timestamps_path.read_text(encoding="utf-8").count("\n") == 1
            assert len(re.findall(r"─── \d{2}:\d{2}:\d{2}", reply_card_text(page))) == 1

            release_second.touch()
            await wait_for_page(page, second_sent.exists, "second commentary record")
            await wait_for_page(
                page,
                lambda: reply_path.read_text(encoding="utf-8").endswith(
                    MOUNTED_COMMENTARY_2
                ),
                "tail to append the second commentary chunk",
            )
            assert process.poll() is None
            assert not terminal_sent.exists()

            # Do not send a watcher event for the second append. Force the same
            # stat-only backstop the one-second countdown calls.
            panel._live_reply_last_probe = time.monotonic() - 2
            panel.maybe_probe_live_reply_drift()
            await wait_for_page(
                page,
                lambda: MOUNTED_COMMENTARY_2 in reply_card_text(page),
                "polling backstop to paint the latest bytes",
            )
            assert reply_card_text(page).count(MOUNTED_COMMENTARY_1) == 1
            assert reply_card_text(page).count(MOUNTED_COMMENTARY_2) == 1
            assert timestamps_path.read_text(encoding="utf-8").count("\n") == 2
            assert len(re.findall(r"─── \d{2}:\d{2}:\d{2}", reply_card_text(page))) == 2
            assert refresh_calls == []

            release_terminal.touch()
            result = await asyncio.wait_for(parser_task, timeout=5)
            assert process.wait(timeout=1) == 0
            assert result[0] == MOUNTED_ANSWER
            assert terminal_sent.exists()
            # The unphased final message committed to the session log must not
            # duplicate the terminal answer: it appears exactly once, below
            # the commentary.
            panel._live_reply_last_probe = time.monotonic() - 2
            panel.maybe_probe_live_reply_drift()
            await wait_for_page(
                page,
                lambda: MOUNTED_ANSWER in reply_card_text(page),
                "final answer below the commentary",
            )
            assert reply_card_text(page).count(MOUNTED_ANSWER) == 1

            # A normal terminal-state display render consumes the final artifact.
            # The provider's terminal text is authoritative and must not be appended
            # a second time on top of the streamed answer.
            selected = page.app._get_selected_agent()
            assert selected is not None
            selected.status = "DONE"
            selected.stop_time = datetime(2026, 10, 3, 12, 1, 0)
            panel.update_display(selected)
            await wait_for_visual_idle(page)
            assert reply_card_text(page).count(MOUNTED_ANSWER) == 1
            assert MOUNTED_COMMENTARY_1 in reply_card_text(page)
            assert MOUNTED_COMMENTARY_2 in reply_card_text(page)
            assert panel._live_reply_source is None
        finally:
            for gate in (release_second, release_terminal):
                gate.touch(exist_ok=True)
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=2)
            if not parser_task.done():
                try:
                    await asyncio.wait_for(parser_task, timeout=3)
                except Exception:
                    pass
