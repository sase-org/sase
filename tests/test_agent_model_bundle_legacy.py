"""Old-bundle compatibility tests: name synthesis and legacy field renames."""

import json
from datetime import datetime

from sase.ace.tui.models.agent import Agent, AgentType
from sase.ace.tui.models.agent_bundle import LEGACY_AGENT_FIELD_NAMES


# --- Old-bundle dismissed-name synthesis (sase-10 phase 5) ---


def test_old_bundle_synthesizes_prefixed_agent_name_from_stop_time() -> None:
    """Bundles missing ``agent_name`` get a prefixed name from stop_time."""
    bundle = {
        "agent_type": AgentType.RUNNING.value,
        "cl_name": "feature_x",
        "project_file": "/tmp/test.sase",
        "status": "DONE",
        "start_time": datetime(2026, 4, 28, 9, 0, 0).isoformat(),
        "stop_time": datetime(2026, 4, 28, 10, 30, 0).isoformat(),
        "raw_suffix": "20260428090000",
    }
    restored = Agent.from_bundle_dict(bundle)
    assert restored.agent_name == "260428.feature_x"


def test_old_bundle_synthesis_falls_back_to_raw_suffix_date() -> None:
    """Without stop_time/start_time, raw_suffix supplies the date and base."""
    bundle = {
        "agent_type": AgentType.RUNNING.value,
        "cl_name": "unknown",
        "project_file": "/tmp/test.sase",
        "status": "DONE",
        "start_time": None,
        "raw_suffix": "20260501123045",
    }
    restored = Agent.from_bundle_dict(bundle)
    assert restored.agent_name == "260501.20260501123045"


def test_old_bundle_synthesis_skips_already_prefixed_name() -> None:
    """Bundles that already carry a prefixed name are left alone."""
    bundle = {
        "agent_type": AgentType.RUNNING.value,
        "cl_name": "foo",
        "project_file": "/tmp/test.sase",
        "status": "DONE",
        "start_time": datetime(2026, 4, 28, 9, 0, 0).isoformat(),
        "raw_suffix": "20260428090000",
        "agent_name": "260428.foo",
    }
    restored = Agent.from_bundle_dict(bundle)
    assert restored.agent_name == "260428.foo"


def test_bundle_preserves_stored_unprefixed_name() -> None:
    """A stored ``agent_name`` without a prefix is permanent and preserved."""
    bundle = {
        "agent_type": AgentType.RUNNING.value,
        "cl_name": "x",
        "project_file": "/tmp/test.sase",
        "status": "DONE",
        "start_time": datetime(2026, 4, 28, 9, 0, 0).isoformat(),
        "raw_suffix": "20260428090000",
        "agent_name": "foo",
    }
    restored = Agent.from_bundle_dict(bundle)
    assert restored.agent_name == "foo"


def test_bundle_preserves_plan_chain_stored_name() -> None:
    """Plan-chain names such as ``by.plan`` are not dismissal-prefixed."""
    bundle = {
        "agent_type": AgentType.RUNNING.value,
        "cl_name": "feature_by",
        "project_file": "/tmp/test.sase",
        "status": "PLAN DONE",
        "start_time": datetime(2026, 5, 9, 12, 41, 56).isoformat(),
        "stop_time": datetime(2026, 5, 9, 13, 6, 29).isoformat(),
        "raw_suffix": "20260509124156",
        "agent_name": "by.plan",
        "role_suffix": ".plan",
    }
    restored = Agent.from_bundle_dict(bundle)
    assert restored.agent_name == "by.plan"


def test_bundle_round_trips_tale_done_status() -> None:
    """A revived tale workflow with ``TALE DONE`` survives bundle round-tripping."""
    bundle = {
        "agent_type": AgentType.RUNNING.value,
        "cl_name": "feature_by",
        "project_file": "/tmp/test.sase",
        "status": "TALE DONE",
        "start_time": datetime(2026, 5, 11, 12, 0, 0).isoformat(),
        "stop_time": datetime(2026, 5, 11, 13, 0, 0).isoformat(),
        "raw_suffix": "20260511120000",
        "agent_name": "by.plan",
        "role_suffix": ".plan",
        "plan_action": "tale",
    }
    restored = Agent.from_bundle_dict(bundle)
    assert restored.status == "TALE DONE"
    assert restored.plan_action == "tale"
    assert restored.agent_name == "by.plan"


def test_old_bundle_synthesis_skips_workflow_children() -> None:
    """Workflow children inherit identity from their parent — leave them alone."""
    bundle = {
        "agent_type": AgentType.WORKFLOW.value,
        "cl_name": "feature",
        "project_file": "/tmp/test.sase",
        "status": "DONE",
        "start_time": datetime(2026, 4, 28, 9, 0, 0).isoformat(),
        "parent_timestamp": "20260428090000",
        "raw_suffix": "20260428090000",
        "step_index": 1,
    }
    restored = Agent.from_bundle_dict(bundle)
    assert restored.agent_name is None


def test_bundle_loads_legacy_pre_rename_fields() -> None:
    """Pre-rename dismissed bundles load through the legacy field table."""
    bundle = {
        "agent_type": AgentType.RUNNING.value,
        "cl_name": "my_feature",
        "project_file": "/tmp/test.sase",
        "status": "DONE",
        "start_time": datetime(2026, 1, 1, 12, 0, 0).isoformat(),
        "agent_name": "crew--code",
        # legacy agent-family spelling: pre-rename bundle field names
        "agent_family": "crew",
        "agent_family_role": "code",
        "agent_family_parallel": False,
        "raw_suffix": "20260101120000",
    }
    restored = Agent.from_bundle_dict(bundle)
    assert restored.agent_session == "crew"
    assert restored.agent_session_role == "code"
    assert restored.agent_session_parallel is False
    # A present new spelling stays authoritative over the legacy one.
    mixed = dict(bundle, agent_session="other", agent_session_role="plan")
    restored_mixed = Agent.from_bundle_dict(mixed)
    assert restored_mixed.agent_session == "other"
    assert restored_mixed.agent_session_role == "plan"


def test_bundle_write_emits_no_legacy_fields() -> None:
    """New dismissed bundles carry only agent_session* field names."""
    agent = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="my_feature",
        project_file="/tmp/test.sase",
        status="DONE",
        start_time=datetime(2026, 1, 1, 12, 0, 0),
        raw_suffix="20260101120000",
        agent_name="crew--code",
        agent_session="crew",
        agent_session_role="code",
        agent_session_parallel=False,
    )
    bundle = agent.to_bundle_dict()
    assert not (set(bundle) & set(LEGACY_AGENT_FIELD_NAMES))
    assert bundle["agent_session"] == "crew"
    assert bundle["agent_session_role"] == "code"
    assert bundle["agent_session_parallel"] is False
    json.dumps(bundle)
