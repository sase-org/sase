"""Agent metadata pager carries non-sase bead-ID prefixes."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from sase.ace.tui.actions.agents._metadata_pager_document import (
    build_agent_metadata_document,
)
from sase.ace.tui.models._agent_associated_plan_types import BeadSummary
from sase.ace.tui.widgets.prompt_panel._agent_display_state import DetailHeaderSummary
from sase.pager.document import PagerOrigin, section_target_spans
from sase.pager.link_scan import LinkSpanKind
from tests.ace.agent_artifact_startup_fixtures import make_agent


def test_agent_metadata_document_carries_non_sase_prefix(tmp_path: Path) -> None:
    agent = make_agent()
    agent.artifacts_dir = str(tmp_path)
    agent.epic_bead_id = "bob-cli-zz"
    agent.phase_bead_id = "bob-cli-zz.1"
    summary = DetailHeaderSummary(
        phase_bead=BeadSummary(
            id="bob-cli-zz.1",
            phase_title="Phase one",
            description=None,
            actual_plan_path=None,
            display_plan_path=None,
            plan_exists=False,
            plan_readable=False,
            epic_title=None,
            size=None,
        )
    )
    with patch(
        "sase.ace.tui.actions.agents._metadata_pager_document.build_detail_header_summary",
        return_value=summary,
    ):
        document = build_agent_metadata_document(agent)

    assert document.origin is PagerOrigin.AGENT
    assert document.sections
    assert all("bob-cli" in section.bead_id_prefixes for section in document.sections)
    bead_sections = [
        section for section in document.sections if section.title == "BEAD"
    ]
    assert bead_sections
    spans = section_target_spans(bead_sections[0], document.origin)
    assert "bob-cli-zz.1" in [
        span.text for span in spans if span.kind == LinkSpanKind.BARE_TOKEN
    ]
