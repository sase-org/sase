from __future__ import annotations

import pytest

from sase.agent.family_attach import FamilyAttachError
from sase.agent.launch_executor import LaunchExecutionContext, execute_launch_plan
from sase.core.agent_launch_facade import plan_fake_fanout


def test_family_attach_prep_failure_prevents_spawn(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    spawned: list[object] = []

    def fail_resolve(
        _directive: object,
        *,
        project_name: str,
        pending_family_parents: object = None,
    ) -> object:
        assert project_name == "sase"
        assert pending_family_parents == []
        raise FamilyAttachError("Cannot attach family member to 'missing'")

    monkeypatch.setattr(
        "sase.agent.family_attach.resolve_family_attach_plan",
        fail_resolve,
    )

    with pytest.raises(FamilyAttachError, match="Cannot attach family member"):
        execute_launch_plan(
            plan_fake_fanout("single", ["%i(missing, reviewer)\nDo work"]),
            LaunchExecutionContext(
                cl_name="sase",
                project_file="/tmp/sase.sase",
                project_name="sase",
                is_home_mode=True,
            ),
            spawn=lambda request: spawned.append(request),  # type: ignore[arg-type]
        )

    assert spawned == []
