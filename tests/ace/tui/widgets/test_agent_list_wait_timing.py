"""Tests for agent-list wait timing rendering."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sase.ace.tui.widgets._agent_list_rendering import format_agent_option
from sase.ace.tui.widgets.prompt_panel._agent_display_parts import build_header_text
from tests.ace.tui.widgets._agent_display_helpers import make_agent


class TestAwareWaitUntilRendering:
    def test_agent_row_renders_concise_wait_until_countdown_when_deps_done(
        self,
    ) -> None:
        now = datetime(2026, 4, 11, 14, 13, 31, tzinfo=UTC)
        wait_until = datetime(2026, 4, 11, 14, 15, 0, tzinfo=UTC).isoformat()
        agent = make_agent(status="WAITING", wait_until=wait_until)

        left, _, _ = format_agent_option(agent, 0, is_selected=False, now=now)

        assert "test_cl (WAITING 1m29s)" in left.plain
        assert "until" not in left.plain
        assert "WAITING (" not in left.plain

    def test_agent_row_keeps_verbose_wait_until_when_deps_pending(self) -> None:
        now = datetime(2026, 4, 11, 14, 13, 31, tzinfo=UTC)
        wait_until = datetime(2026, 4, 11, 14, 15, 0, tzinfo=UTC).isoformat()
        agent = make_agent(
            status="WAITING",
            waiting_for=["dep"],
            wait_until=wait_until,
        )

        left, _, _ = format_agent_option(
            agent,
            0,
            is_selected=False,
            now=now,
            wait_deps_satisfied=False,
        )

        assert "test_cl (WAITING (until 14:15, 1m29s))" in left.plain

    def test_header_renders_aware_wait_until_countdown(self) -> None:
        wait_until = (datetime.now(UTC) + timedelta(hours=1)).isoformat()
        agent = make_agent(status="WAITING", wait_until=wait_until)

        header, _ = build_header_text(agent, cheap=True)

        assert "Wait: [time] until " in header.plain
        assert " left)" in header.plain


class TestRelativeWaitDurationRendering:
    def test_header_omits_duration_countdown_while_agent_deps_pending(self) -> None:
        agent = make_agent(
            status="WAITING",
            waiting_for=["dep"],
            wait_duration=300,
            start_time=datetime.now() + timedelta(minutes=5),
        )

        header, _ = build_header_text(agent, cheap=True)

        wait_line = next(
            line for line in header.plain.splitlines() if line.startswith("Wait: ")
        )
        assert wait_line == "Wait: [agents] dep"
        assert "      [time]   5m" in header.plain

    def test_agent_row_omits_duration_countdown_while_agent_deps_pending(
        self,
    ) -> None:
        agent = make_agent(
            status="WAITING",
            waiting_for=["dep"],
            wait_duration=300,
            start_time=datetime.now() + timedelta(minutes=5),
        )

        left, _, _ = format_agent_option(
            agent,
            0,
            is_selected=False,
            wait_deps_satisfied=True,
        )

        assert left.plain.endswith("test_cl (WAITING +5m)")

    def test_agent_row_renders_duration_countdown_after_wait_until_written(
        self,
    ) -> None:
        now = datetime(2026, 4, 11, 14, 13, 31, tzinfo=UTC)
        wait_until = datetime(2026, 4, 11, 14, 15, 0, tzinfo=UTC).isoformat()
        agent = make_agent(
            status="WAITING",
            waiting_for=["dep"],
            wait_duration=300,
            wait_until=wait_until,
        )

        left, _, _ = format_agent_option(
            agent,
            0,
            is_selected=False,
            now=now,
            wait_deps_satisfied=True,
        )

        assert "test_cl (WAITING 1m29s)" in left.plain
        assert "+5m" not in left.plain

    def test_root_wait_display_source_renders_static_duration_hint(self) -> None:
        root = make_agent(status="WAITING")
        child = make_agent(
            status="WAITING",
            cl_name="child",
            waiting_for=["dep"],
            wait_duration=300,
        )
        root.wait_display_source = child

        left, _, _ = format_agent_option(root, 0, is_selected=False)

        assert left.plain.endswith("test_cl (WAITING +5m)")

    def test_root_wait_display_source_renders_live_countdown(self) -> None:
        now = datetime(2026, 4, 11, 14, 13, 31, tzinfo=UTC)
        wait_until = datetime(2026, 4, 11, 14, 15, 0, tzinfo=UTC).isoformat()
        root = make_agent(status="WAITING")
        child = make_agent(
            status="WAITING",
            cl_name="child",
            waiting_for=["dep"],
            wait_duration=300,
            wait_until=wait_until,
        )
        root.wait_display_source = child

        left, _, _ = format_agent_option(
            root,
            0,
            is_selected=False,
            now=now,
            wait_deps_satisfied=True,
        )

        assert "test_cl (WAITING 1m29s)" in left.plain
        assert "+5m" not in left.plain

    def test_root_wait_display_source_header_matches_child(self) -> None:
        root = make_agent(status="WAITING")
        child = make_agent(
            status="WAITING",
            cl_name="child",
            waiting_for=["dep"],
            wait_duration=300,
        )
        root.wait_display_source = child

        root_header, _ = build_header_text(root, cheap=True)
        child_header, _ = build_header_text(child, cheap=True)

        root_wait = next(
            line for line in root_header.plain.splitlines() if line.startswith("Wait: ")
        )
        child_wait = next(
            line
            for line in child_header.plain.splitlines()
            if line.startswith("Wait: ")
        )
        assert root_wait == child_wait == "Wait: [agents] dep"
        assert "      [time]   5m" in root_header.plain
        assert "      [time]   5m" in child_header.plain

    def test_pure_duration_wait_still_renders_countdown(self) -> None:
        now = datetime(2026, 4, 11, 14, 13, 31)
        agent = make_agent(
            status="WAITING",
            wait_duration=300,
            start_time=datetime(2026, 4, 11, 14, 10, 0),
        )
        header_agent = make_agent(
            status="WAITING",
            wait_duration=300,
            start_time=datetime.now(),
        )

        left, _, _ = format_agent_option(agent, 0, is_selected=False, now=now)
        header, _ = build_header_text(header_agent, cheap=True)

        assert "test_cl (WAITING 1m29s)" in left.plain
        assert "WAITING (" not in left.plain
        assert "Wait: [time] 5m (" in header.plain
        assert " left)" in header.plain

    def test_family_child_header_renders_waiting_for_like_root_waiting_row(
        self,
    ) -> None:
        agent = make_agent(
            status="WAITING",
            parent_timestamp="parent-ts",
            waiting_for=["parent"],
            wait_duration=120,
        )

        header, _ = build_header_text(agent, cheap=True)

        assert agent.is_family_member_child
        assert "Patch: test_cl" in header.plain
        assert "Step: " not in header.plain
        assert "Wait: [agents] parent\n      [time]   2m" in header.plain
