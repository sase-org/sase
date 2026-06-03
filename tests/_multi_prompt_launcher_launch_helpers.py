"""Helpers for multi-prompt launcher launch tests."""


def spawn_result_with_planned_name(**kwargs: object):
    from sase.agent.launch_types import AgentLaunchResult

    extra_env = kwargs.get("extra_env") or {}
    planned_name = (
        extra_env.get("SASE_AGENT_PLANNED_NAME")
        if isinstance(extra_env, dict)
        else None
    )
    return AgentLaunchResult(
        pid=1,
        workspace_num=int(kwargs.get("workspace_num", 0)),  # type: ignore[arg-type]
        workspace_dir=str(kwargs.get("workspace_dir", "/ws")),
        output_path="/out.txt",
        timestamp=str(kwargs.get("timestamp", "")),
        project_name=str(kwargs.get("project_name", "")),
        agent_name=planned_name if isinstance(planned_name, str) else None,
    )
