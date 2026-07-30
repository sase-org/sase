"""Tests for the cross-agent ``agents`` output-variable Jinja context."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

from sase.agent.output_variable_context import (
    SASE_AGENT_VAR_UPSTREAMS_ENV,
    _agent_key_for_output_variables,
    build_agent_output_variable_context,
    build_agent_var_upstream_record,
    encode_agent_var_upstreams,
)
from tests._agent_names_fixtures import make_agent


def test_agent_name_template_exposes_base_key() -> None:
    assert (
        _agent_key_for_output_variables(
            agent_name="build-7",
            agent_name_template="build-@",
        )
        == "build"
    )


def test_dotted_agent_name_template_exposes_flat_dotted_key() -> None:
    assert (
        _agent_key_for_output_variables(
            agent_name="research.2.final",
            agent_name_template="research.@.final",
        )
        == "research.final"
    )


def test_plain_hyphenated_agent_name_is_used_verbatim() -> None:
    assert _agent_key_for_output_variables(agent_name="build-agent") == "build-agent"


def test_digit_leading_dotted_agent_name_is_used_verbatim() -> None:
    assert _agent_key_for_output_variables(agent_name="0n.cld") == "0n.cld"


def test_named_producer_loads_under_agents_dict(tmp_path: Path) -> None:
    with patch.object(Path, "home", return_value=tmp_path):
        upstream = build_agent_var_upstream_record(
            agent_name="build",
            project_name="proj",
            workflow_timestamp="260501_120000",
        )

    artifacts_dir = Path(str(upstream["artifacts_dir"]))
    artifacts_dir.mkdir(parents=True)
    (artifacts_dir / "agent_meta.json").write_text(
        json.dumps(
            {
                "name": "build",
                "output_variables": {"report_path": "reports/final.md"},
            }
        ),
        encoding="utf-8",
    )

    context = build_agent_output_variable_context(
        upstreams_json=encode_agent_var_upstreams([upstream]),
    )

    assert context == {"agents": {"build": {"report_path": "reports/final.md"}}}


def test_agent_name_template_upstream_uses_stable_base_key(tmp_path: Path) -> None:
    with patch.object(Path, "home", return_value=tmp_path):
        upstream = build_agent_var_upstream_record(
            agent_name="build-1",
            agent_name_template="build-@",
            project_name="proj",
            workflow_timestamp="260501_120000",
        )

    artifacts_dir = Path(str(upstream["artifacts_dir"]))
    artifacts_dir.mkdir(parents=True)
    (artifacts_dir / "agent_meta.json").write_text(
        json.dumps(
            {
                "name": "build-1",
                "agent_name_template": "build-@",
                "output_variables": {"report_path": "reports/final.md"},
            }
        ),
        encoding="utf-8",
    )

    context = build_agent_output_variable_context(
        upstreams_json=encode_agent_var_upstreams([upstream]),
    )

    assert context == {"agents": {"build": {"report_path": "reports/final.md"}}}


def test_dotted_agent_name_template_uses_flat_dotted_key(tmp_path: Path) -> None:
    with patch.object(Path, "home", return_value=tmp_path):
        upstream = build_agent_var_upstream_record(
            agent_name="research.1.final",
            agent_name_template="research.@.final",
            project_name="proj",
            workflow_timestamp="260501_120000",
        )

    artifacts_dir = Path(str(upstream["artifacts_dir"]))
    artifacts_dir.mkdir(parents=True)
    (artifacts_dir / "agent_meta.json").write_text(
        json.dumps(
            {
                "name": "research.1.final",
                "agent_name_template": "research.@.final",
                "output_variables": {"report_path": "reports/final.md"},
            }
        ),
        encoding="utf-8",
    )

    context = build_agent_output_variable_context(
        upstreams_json=encode_agent_var_upstreams([upstream]),
    )

    assert context == {
        "agents": {"research.final": {"report_path": "reports/final.md"}}
    }


def test_digit_leading_dotted_fanout_uses_raw_key(tmp_path: Path) -> None:
    with patch.object(Path, "home", return_value=tmp_path):
        upstream = build_agent_var_upstream_record(
            agent_name="0n.cld",
            project_name="proj",
            workflow_timestamp="260501_120000",
        )

    artifacts_dir = Path(str(upstream["artifacts_dir"]))
    artifacts_dir.mkdir(parents=True)
    (artifacts_dir / "agent_meta.json").write_text(
        json.dumps(
            {
                "name": "0n.cld",
                "output_variables": {"report_path": "reports/final.md"},
            }
        ),
        encoding="utf-8",
    )

    context = build_agent_output_variable_context(
        upstreams_json=encode_agent_var_upstreams([upstream]),
    )

    assert context == {"agents": {"0n.cld": {"report_path": "reports/final.md"}}}


def test_later_upstream_overrides_same_key(tmp_path: Path) -> None:
    with patch.object(Path, "home", return_value=tmp_path):
        first = build_agent_var_upstream_record(
            agent_name="build",
            project_name="proj",
            workflow_timestamp="260501_120000",
        )
        second = build_agent_var_upstream_record(
            agent_name="build",
            project_name="proj",
            workflow_timestamp="260501_120001",
        )

    for record, value in ((first, "old.txt"), (second, "new.txt")):
        artifacts_dir = Path(str(record["artifacts_dir"]))
        artifacts_dir.mkdir(parents=True)
        (artifacts_dir / "agent_meta.json").write_text(
            json.dumps({"name": "build", "output_variables": {"path": value}}),
            encoding="utf-8",
        )

    context = build_agent_output_variable_context(
        upstreams_json=encode_agent_var_upstreams([first, second]),
    )

    assert context == {"agents": {"build": {"path": "new.txt"}}}


def test_empty_producers_create_no_agents_entry(tmp_path: Path) -> None:
    with patch.object(Path, "home", return_value=tmp_path):
        upstream = build_agent_var_upstream_record(
            agent_name="build",
            project_name="proj",
            workflow_timestamp="260501_120000",
        )

    # No agent_meta.json on disk: producer wrote nothing.
    context = build_agent_output_variable_context(
        upstreams_json=encode_agent_var_upstreams([upstream]),
    )

    assert context == {}


def test_waited_agent_variables_load_as_fallback_context(tmp_path: Path) -> None:
    agent_dir = make_agent(
        tmp_path,
        "proj",
        "20260501120000",
        "build-1",
        done=True,
        outcome="completed",
    )
    meta_path = agent_dir / "agent_meta.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    meta["agent_name_template"] = "build-@"
    meta["output_variables"] = {"report_path": "reports/build.md"}
    meta_path.write_text(json.dumps(meta), encoding="utf-8")

    with patch.object(Path, "home", return_value=tmp_path):
        context = build_agent_output_variable_context(
            upstreams_json=None,
            wait_names=["build-1"],
        )

    assert context == {"agents": {"build": {"report_path": "reports/build.md"}}}


def test_spawn_env_scrubber_removes_inherited_upstream_context() -> None:
    from sase.agent.launch_spawn import _remove_inherited_agent_identity_env

    env = {SASE_AGENT_VAR_UPSTREAMS_ENV: "[]", "OTHER": "1"}

    _remove_inherited_agent_identity_env(env)

    assert env == {"OTHER": "1"}
