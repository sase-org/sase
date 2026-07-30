"""Tests for xprompt metadata in the agent prompt panel."""

import json
from pathlib import Path
from unittest.mock import patch

from rich.text import Text

from sase.ace.tui.widgets.prompt_panel import AgentPromptPanel, load_xprompts_used
from sase.ace.tui.widgets.prompt_panel._agent_display_parts import (
    build_detail_header_summary,
    build_header_text,
    cache_detail_header_summary,
)
from sase.ace.tui.widgets.prompt_panel._agent_xprompts import (
    _COLOR_HEADER,
    _COLOR_PART,
    _COLOR_SWARM,
    _COLOR_WORKFLOW,
)
from tests.ace.tui.widgets._agent_display_helpers import make_workflow_agent


def _styles_over(header: Text, substring: str) -> set[str]:
    start = header.plain.index(substring)
    end = start + len(substring)
    return {
        str(span.style)
        for span in header.spans
        if span.start < end and span.end > start
    }


def testload_xprompts_used_empty(tmp_path: Path) -> None:
    """No xprompts.json file returns None."""
    agent = make_workflow_agent(artifacts_dir=str(tmp_path))
    result = load_xprompts_used(agent)

    assert result is None


def testload_xprompts_used_no_artifacts_dir() -> None:
    """Agent with no artifacts_dir returns None."""
    agent = make_workflow_agent(artifacts_dir=None)
    result = load_xprompts_used(agent)

    assert result is None


def test_load_xprompts_used_child_step_does_not_fall_back_to_shared(
    tmp_path: Path,
) -> None:
    """A child step with no step file must not read the shared xprompts.json.

    The shared file holds launch/root metadata; a workflow-child row whose own
    step captured no xprompt usage shows nothing rather than the root's data.
    """
    (tmp_path / "xprompts.json").write_text(
        json.dumps(
            [
                {
                    "name": "plan",
                    "kind": "part",
                    "positional": [],
                    "named": {},
                    "tags": [],
                }
            ]
        )
    )

    agent = make_workflow_agent(
        artifacts_dir=str(tmp_path),
        parent_workflow="olcr",
        step_name="build",
    )

    assert load_xprompts_used(agent) is None


def test_load_xprompts_used_root_reads_shared(tmp_path: Path) -> None:
    """A non-step (root) agent reads the shared xprompts.json."""
    records = [
        {
            "name": "plan",
            "kind": "part",
            "positional": [],
            "named": {},
            "tags": [],
        }
    ]
    (tmp_path / "xprompts.json").write_text(json.dumps(records))

    agent = make_workflow_agent(artifacts_dir=str(tmp_path))

    assert load_xprompts_used(agent) == records


def test_xprompts_displayed_from_header_summary(tmp_path: Path) -> None:
    """Precomputed header summaries can render xprompt metadata."""
    metadata = [
        {
            "name": "propose",
            "kind": "workflow",
            "positional": [],
            "named": {"note": "blah"},
            "tags": [],
        },
        {
            "name": "cl",
            "kind": "workflow",
            "positional": [],
            "named": {},
            "tags": [],
        },
        {
            "name": "review_checklist",
            "kind": "part",
            "positional": [],
            "named": {},
            "tags": [],
        },
    ]
    metadata_file = tmp_path / "xprompts_main.json"
    metadata_file.write_text(json.dumps(metadata))

    agent = make_workflow_agent(
        artifacts_dir=str(tmp_path),
        parent_workflow="olcr",
        step_name="main",
    )

    header, _ = build_header_text(
        agent,
        summary=build_detail_header_summary(agent),
    )

    assert "Xprompts: 2 workflows · 1 part" in header.plain
    assert "⌘ #propose  note=blah" in header.plain
    assert "⌘ #cl" in header.plain
    assert "▣ #review_checklist" in header.plain


def test_xprompt_part_value_uses_distinct_style(tmp_path: Path) -> None:
    """Part values render in a distinct color, not the metadata-label blue."""
    metadata = [
        {
            "name": "propose",
            "kind": "workflow",
            "positional": [],
            "named": {},
            "tags": [],
        },
        {
            "name": "review_checklist",
            "kind": "part",
            "positional": [],
            "named": {},
            "tags": [],
        },
    ]
    metadata_file = tmp_path / "xprompts_main.json"
    metadata_file.write_text(json.dumps(metadata))

    agent = make_workflow_agent(
        artifacts_dir=str(tmp_path),
        parent_workflow="olcr",
        step_name="main",
    )

    header, _ = build_header_text(
        agent,
        summary=build_detail_header_summary(agent),
    )

    assert _COLOR_HEADER in _styles_over(header, "Xprompts:")
    assert _COLOR_WORKFLOW in _styles_over(header, "#propose")
    assert _COLOR_PART in _styles_over(header, "#review_checklist")
    # The part value must not read like a metadata field label.
    assert _COLOR_PART != _COLOR_HEADER
    assert _COLOR_HEADER not in _styles_over(header, "#review_checklist")


def test_swarm_xprompt_gets_own_glyph_style_and_summary_count(
    tmp_path: Path,
) -> None:
    """The originating swarm reads as a swarm, not as a part."""
    metadata = [
        {
            "name": "research_swarm",
            "kind": "swarm",
            "positional": [],
            "named": {},
            "tags": ["research"],
        },
        {
            "name": "review_checklist",
            "kind": "part",
            "positional": [],
            "named": {},
            "tags": [],
        },
    ]
    metadata_file = tmp_path / "xprompts_main.json"
    metadata_file.write_text(json.dumps(metadata))

    agent = make_workflow_agent(
        artifacts_dir=str(tmp_path),
        parent_workflow="olcr",
        step_name="main",
    )

    header, _ = build_header_text(
        agent,
        summary=build_detail_header_summary(agent),
    )

    assert "Xprompts: 1 swarm · 1 part" in header.plain
    assert "❋ #research_swarm" in header.plain
    assert _COLOR_SWARM in _styles_over(header, "#research_swarm")
    assert _COLOR_PART not in _styles_over(header, "#research_swarm")


def test_swarm_only_agent_summarizes_as_a_swarm(tmp_path: Path) -> None:
    """A swarm-only record must not fall back to the generic xprompt count."""
    metadata_file = tmp_path / "xprompts_main.json"
    metadata_file.write_text(
        json.dumps(
            [
                {
                    "name": "research_swarm",
                    "kind": "swarm",
                    "positional": [],
                    "named": {},
                    "tags": [],
                }
            ]
        )
    )

    agent = make_workflow_agent(
        artifacts_dir=str(tmp_path),
        parent_workflow="olcr",
        step_name="main",
    )

    header, _ = build_header_text(
        agent,
        summary=build_detail_header_summary(agent),
    )

    assert "Xprompts: 1 swarm" in header.plain
    assert "1 xprompt" not in header.plain


def test_update_display_renders_xprompts_after_detail_settles(
    tmp_path: Path,
) -> None:
    """Full prompt updates render precomputed xprompt metadata."""
    metadata_file = tmp_path / "xprompts_main.json"
    metadata_file.write_text(
        json.dumps(
            [
                {
                    "name": "propose",
                    "kind": "workflow",
                    "positional": [],
                    "named": {},
                    "tags": [],
                }
            ]
        )
    )

    agent = make_workflow_agent(
        artifacts_dir=str(tmp_path),
        parent_workflow="olcr",
        step_name="main",
    )
    panel = AgentPromptPanel.__new__(AgentPromptPanel)

    with patch.object(panel, "update") as mock_update:
        panel.update_display(agent)
        rendered = mock_update.call_args[0][0]
        assert "Xprompts: 1 workflow" not in str(rendered)

        cache_detail_header_summary(panel, agent, build_detail_header_summary(agent))
        panel.update_display(agent)

    assert mock_update.called
    rendered = mock_update.call_args[0][0]
    assert "Xprompts: 1 workflow" in str(rendered)
    assert "⌘ #propose" in str(rendered)
