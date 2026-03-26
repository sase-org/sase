"""Tests for meta_changespec vs meta_project priority in AGENT DETAILS header."""

from datetime import datetime

from sase.ace.tui.models.agent import Agent, AgentType
from sase.ace.tui.widgets.prompt_panel._agent_display import AgentDisplayMixin


def _make_agent(**overrides) -> Agent:  # type: ignore[no-untyped-def]
    defaults = {
        "agent_type": AgentType.RUNNING,
        "cl_name": "proj_feat_1",
        "project_file": "/fake/proj.gp",
        "status": "DONE",
        "start_time": datetime(2026, 1, 1, 12, 0, 0),
    }
    defaults.update(overrides)
    return Agent(**defaults)


class _TestableDisplay(AgentDisplayMixin):
    """Minimal concrete subclass to test _build_header_text."""

    def update(self, content):  # type: ignore[no-untyped-def]
        pass


class TestMetaChangespecPriority:
    """meta_changespec should be preferred over meta_project when both present."""

    def test_changespec_preferred_over_project(self) -> None:
        agent = _make_agent(
            step_output={
                "meta_project": "my_project",
                "meta_changespec": "proj_feat_1",
            },
        )
        display = _TestableDisplay()
        header, _ = display._build_header_text(agent)
        text = header.plain

        assert "ChangeSpec: proj_feat_1" in text
        assert "Project: my_project" not in text

    def test_project_shown_when_no_changespec(self) -> None:
        agent = _make_agent(
            step_output={"meta_project": "my_project"},
        )
        display = _TestableDisplay()
        header, _ = display._build_header_text(agent)
        text = header.plain

        assert "Project: my_project" in text
        assert "ChangeSpec:" not in text

    def test_changespec_shown_alone(self) -> None:
        agent = _make_agent(
            step_output={"meta_changespec": "proj_feat_1"},
        )
        display = _TestableDisplay()
        header, _ = display._build_header_text(agent)
        text = header.plain

        assert "ChangeSpec: proj_feat_1" in text

    def test_changespec_with_cl_num(self) -> None:
        agent = _make_agent(
            step_output={
                "meta_project": "my_project",
                "meta_changespec": "proj_feat_1",
            },
            cl_num="12345",
        )
        display = _TestableDisplay()
        header, _ = display._build_header_text(agent)
        text = header.plain

        assert "ChangeSpec: proj_feat_1 (12345)" in text
        assert "Project:" not in text
