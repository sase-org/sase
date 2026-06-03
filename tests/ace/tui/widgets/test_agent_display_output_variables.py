"""Tests for agent display output variables."""

from __future__ import annotations

import json
from pathlib import Path

from sase.ace.tui.models._loaders._meta_enrichment import (
    enrich_agent_from_meta,
    enrich_agent_from_meta_wire,
)
from sase.ace.tui.widgets.prompt_panel._agent_artifacts import AgentArtifactPath
from sase.ace.tui.widgets.prompt_panel._agent_display_parts import (
    _DetailHeaderSummary,
    build_header_text,
)
from sase.core.agent_scan_wire import AgentMetaWire
from tests.ace.tui.widgets._agent_display_helpers import make_agent
from tests.ace.tui.widgets._agent_display_metadata_helpers import (
    assert_dim_divider_before,
)


def test_output_variables_section_absent_when_empty() -> None:
    agent = make_agent()

    header, _ = build_header_text(agent, cheap=True)

    assert "OUTPUT VARIABLES" not in header.plain


def test_output_variables_section_orders_before_artifacts_and_workflow_variables() -> (
    None
):
    agent = make_agent(
        output_variables={
            "z_status": "ok",
            "a_notes": "line one\nline two",
        },
        step_output={"meta_result": "ready"},
    )
    summary = _DetailHeaderSummary(
        artifact_paths=[
            AgentArtifactPath(
                display_path="artifact.txt",
                actual_path="/tmp/artifact.txt",
            )
        ],
    )

    header, _ = build_header_text(agent, cheap=False, summary=summary)
    plain = header.plain

    assert "OUTPUT VARIABLES\n" in plain
    assert "a_notes:\n  line one\n  line two\n" in plain
    assert "z_status: ok\n" in plain
    assert plain.index("a_notes:") < plain.index("z_status:")
    assert plain.index("OUTPUT VARIABLES\n") < plain.index("Artifacts:\n")
    assert plain.index("OUTPUT VARIABLES\n") < plain.index("WORKFLOW VARIABLES\n")
    assert_dim_divider_before(header, "OUTPUT VARIABLES\n")


def test_filesystem_and_wire_output_variables_render_identically(
    tmp_path: Path,
) -> None:
    variables = {
        "report_path": "/tmp/report.md",
        "summary": "first line\nsecond line",
    }
    (tmp_path / "agent_meta.json").write_text(
        json.dumps(
            {
                "output_variables": {
                    **variables,
                    "ignored_count": 2,
                }
            }
        ),
        encoding="utf-8",
    )
    filesystem_agent = make_agent()
    wire_agent = make_agent()

    enrich_agent_from_meta(filesystem_agent, str(tmp_path))
    enrich_agent_from_meta_wire(
        wire_agent,
        AgentMetaWire(output_variables=variables),
        None,
        None,
    )

    filesystem_header, _ = build_header_text(filesystem_agent, cheap=True)
    wire_header, _ = build_header_text(wire_agent, cheap=True)

    assert filesystem_agent.output_variables == variables
    assert filesystem_header.plain == wire_header.plain
