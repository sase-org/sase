"""Tests for agent display output variables."""

from __future__ import annotations

import json
from pathlib import Path

from sase.ace.tui.models._loaders._meta_enrichment import (
    enrich_agent_from_meta,
    enrich_agent_from_meta_wire,
)
from sase.ace.tui.models.agent import Agent
from sase.ace.tui.widgets.prompt_panel._artifact_files import ArtifactFilePath
from sase.ace.tui.widgets.prompt_panel._agent_display_parts import (
    _DetailHeaderSummary,
    build_header_text,
)
from sase.core.agent_scan_wire import AgentMetaWire
from tests.ace.tui.widgets._agent_display_helpers import make_agent
from tests.ace.tui.widgets._agent_display_metadata_helpers import (
    assert_dim_divider_before,
    assert_logical_section_is_compact,
    assert_rendered_section_is_compact,
)


def _family_root(**overrides: object) -> Agent:
    defaults: dict[str, object] = {
        "cl_name": "output-var-family",
        "raw_suffix": "20260708090000",
        "agent_name": "output-var-family",
        "role_suffix": "--plan",
        "agent_family": "output-var-family",
        "agent_family_role": "root",
        "plan_chain_root": True,
    }
    defaults.update(overrides)
    if "tag" in defaults:
        defaults["tribe"] = defaults.pop("tag")
    return make_agent(**defaults)


def _family_child(
    tmp_path: Path,
    name: str,
    *,
    role_suffix: str,
    agent_family_role: str,
    output_variables: dict[str, str],
) -> Agent:
    artifacts_dir = tmp_path / name
    artifacts_dir.mkdir()
    return make_agent(
        cl_name=f"output-var-family--{name}",
        raw_suffix=f"20260708090{name}",
        parent_timestamp="20260708090000",
        artifacts_dir=str(artifacts_dir),
        agent_name=f"output-var-family--{name}",
        agent_family="output-var-family",
        agent_family_role=agent_family_role,
        role_suffix=role_suffix,
        output_variables=output_variables,
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
        artifact_file_paths=[
            ArtifactFilePath(
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
    assert plain.index("OUTPUT VARIABLES\n") < plain.index("Files:\n")
    assert plain.index("OUTPUT VARIABLES\n") < plain.index("WORKFLOW VARIABLES\n")
    assert_dim_divider_before(header, "OUTPUT VARIABLES\n")
    assert_logical_section_is_compact(header, "OUTPUT VARIABLES", "a_notes:")
    assert_logical_section_is_compact(header, "WORKFLOW VARIABLES", "Result:")
    assert_rendered_section_is_compact(header, "OUTPUT VARIABLES", "a_notes:")
    assert_rendered_section_is_compact(header, "WORKFLOW VARIABLES", "Result:")


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


def test_output_variables_aggregate_two_children_distinct_keys(
    tmp_path: Path,
) -> None:
    root = _family_root()
    coder = _family_child(
        tmp_path,
        "coder",
        role_suffix="--code",
        agent_family_role="code",
        output_variables={"build_report": "/tmp/build.md"},
    )
    question = _family_child(
        tmp_path,
        "question",
        role_suffix="--q",
        agent_family_role="q",
        output_variables={"answer_path": "/tmp/answer.md"},
    )
    root.followup_agents = [coder, question]

    header, _ = build_header_text(root, cheap=True)
    plain = header.plain

    assert "OUTPUT VARIABLES · 2 agents\n" in plain
    assert "coder  build_report: /tmp/build.md\n" in plain
    assert "q      answer_path: /tmp/answer.md\n" in plain


def test_output_variables_keep_same_key_from_multiple_children(
    tmp_path: Path,
) -> None:
    root = _family_root()
    coder = _family_child(
        tmp_path,
        "coder",
        role_suffix="--code",
        agent_family_role="code",
        output_variables={"result_path": "/tmp/build-result.md"},
    )
    question = _family_child(
        tmp_path,
        "question",
        role_suffix="--q",
        agent_family_role="q",
        output_variables={"result_path": "/tmp/question-result.md"},
    )
    root.followup_agents = [coder, question]

    header, _ = build_header_text(root, cheap=True)
    plain = header.plain

    assert "coder  result_path: /tmp/build-result.md\n" in plain
    assert "q      result_path: /tmp/question-result.md\n" in plain


def test_output_variables_root_without_vars_aggregates_children(
    tmp_path: Path,
) -> None:
    root = _family_root()
    coder = _family_child(
        tmp_path,
        "coder",
        role_suffix="--code",
        agent_family_role="code",
        output_variables={"coder_result": "ready"},
    )
    commit = _family_child(
        tmp_path,
        "commit",
        role_suffix="--commit",
        agent_family_role="commit",
        output_variables={"commit_sha": "abc1234"},
    )
    root.followup_agents = [coder, commit]

    header, _ = build_header_text(root, cheap=True)
    plain = header.plain

    assert "OUTPUT VARIABLES · 2 agents\n" in plain
    assert "coder  coder_result: ready\n" in plain
    assert "commit commit_sha: abc1234\n" in plain


def test_output_variables_root_and_child_are_attributed(
    tmp_path: Path,
) -> None:
    root = _family_root(output_variables={"plan_path": "/tmp/plan.md"})
    coder = _family_child(
        tmp_path,
        "coder",
        role_suffix="--code",
        agent_family_role="code",
        output_variables={"code_path": "/tmp/code.md"},
    )
    root.followup_agents = [coder]

    header, _ = build_header_text(root, cheap=True)
    plain = header.plain

    assert "OUTPUT VARIABLES · 2 agents\n" in plain
    assert "plan   plan_path: /tmp/plan.md\n" in plain
    assert "coder  code_path: /tmp/code.md\n" in plain


def test_output_variables_single_contributor_stays_flat(
    tmp_path: Path,
) -> None:
    root_only = _family_root(output_variables={"only": "root"})
    child_only_root = _family_root(agent_name="child-only-family")
    coder = _family_child(
        tmp_path,
        "coder",
        role_suffix="--code",
        agent_family_role="code",
        output_variables={"only": "child"},
    )
    child_only_root.followup_agents = [coder]

    root_header, _ = build_header_text(root_only, cheap=True)
    child_header, _ = build_header_text(child_only_root, cheap=True)

    assert "OUTPUT VARIABLES ·" not in root_header.plain
    assert "plan   only: root\n" not in root_header.plain
    assert "only: root\n" in root_header.plain
    assert "OUTPUT VARIABLES ·" not in child_header.plain
    assert "coder  only: child\n" not in child_header.plain
    assert "only: child\n" in child_header.plain


def test_output_variables_multiline_value_aligns_under_role_gutter(
    tmp_path: Path,
) -> None:
    root = _family_root()
    coder = _family_child(
        tmp_path,
        "coder",
        role_suffix="--code",
        agent_family_role="code",
        output_variables={"notes": "line one\nline two"},
    )
    question = _family_child(
        tmp_path,
        "question",
        role_suffix="--q",
        agent_family_role="q",
        output_variables={"answer": "ready"},
    )
    root.followup_agents = [coder, question]

    header, _ = build_header_text(root, cheap=True)

    assert "coder  notes:\n         line one\n         line two\n" in header.plain


def test_output_variables_order_root_then_followups_and_sorted_keys(
    tmp_path: Path,
) -> None:
    root = _family_root(output_variables={"z_root": "last", "a_root": "first"})
    coder = _family_child(
        tmp_path,
        "coder",
        role_suffix="--code",
        agent_family_role="code",
        output_variables={"z_child": "last", "a_child": "first"},
    )
    root.followup_agents = [coder]

    header, _ = build_header_text(root, cheap=True)
    plain = header.plain

    assert plain.index("plan   a_root: first") < plain.index("plan   z_root: last")
    assert plain.index("plan   z_root: last") < plain.index("coder  a_child: first")
    assert plain.index("coder  a_child: first") < plain.index("coder  z_child: last")
