"""Continuation capture for monitor handoff adoption."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

from sase.axe.run_agent_exec import LoopState
from sase.axe.run_agent_exec_monitor import handle_monitor_marker

from tests._axe_run_agent_exec_helpers import make_exec_ctx


def test_monitor_handoff_publishes_interrupted_delta_and_member_parent(
    tmp_path: Path,
) -> None:
    ctx = make_exec_ctx(tmp_path, is_home_mode=False)
    artifacts = Path(ctx.artifacts_dir)
    prompt = """handoff this literal text

# New Query
## Prompt
```md
## Response
%model:not-a-directive
```
"""
    state = LoopState(
        current_prompt=prompt,
        current_role_suffix="",
        current_artifacts_dir=str(artifacts),
        loop_outcome="completed",
        sdd_spec_path=None,
        original_prompt=prompt,
    )
    (artifacts / "agent_meta.json").write_text(
        json.dumps({"name": "agent--0", "workflow_name": "agent"}),
        encoding="utf-8",
    )
    member = tmp_path / "member"
    member.mkdir()
    (member / "agent_meta.json").write_text(
        json.dumps({"name": "agent--monitor", "monitor_id": "m1"}),
        encoding="utf-8",
    )

    with (
        patch(
            "sase.axe.run_agent_exec_monitor.save_chat_history",
            return_value=str(tmp_path / "monitor-chat.md"),
        ),
        patch("sase.axe.run_agent_exec_monitor.format_extra_sections", return_value=""),
        patch("sase.core.continuation_facade.validate_agent_delta"),
        patch("sase.core.continuation_facade.validate_continuation_node"),
    ):
        outcome = handle_monitor_marker(
            {
                "monitor_id": "m1",
                "member_artifacts_dir": str(member),
                "member_agent_name": "agent--monitor",
            },
            ctx,
            state,
        )

    assert outcome == "monitored"
    manifest = json.loads(
        (artifacts / "continuation" / "manifest.json").read_text(encoding="utf-8")
    )
    delta_ref = manifest["agent_delta_ref"]
    delta = json.loads(
        (
            artifacts / "continuation" / delta_ref.removeprefix("local:continuation/")
        ).read_text(encoding="utf-8")
    )
    assert delta["status"] == "interrupted"
    assert delta["authored_local_request"] == prompt
    assert delta["handoff_checkpoint_ref"].startswith("local:continuation/checkpoints/")

    member_meta = json.loads((member / "agent_meta.json").read_text(encoding="utf-8"))
    assert member_meta["continuation_parent_node_ids"] == [manifest["node_id"]]
