"""Pluggy hook specifications for workspace provider plugins."""

from dataclasses import dataclass, field

import pluggy

hookspec = pluggy.HookspecMarker("sase_workspace")
hookimpl = pluggy.HookimplMarker("sase_workspace")


@dataclass
class ResolvedRef:
    """Result of resolving a workspace reference (e.g. ``#gh``, ``#git``)."""

    project_file: str
    project_name: str
    primary_workspace_dir: str
    checkout_target: str
    extra: dict[str, str] = field(default_factory=dict)


class WorkspaceHookSpec:
    """Hook specifications for workspace provider plugins.

    Every method uses ``firstresult=True`` so pluggy returns the first
    non-``None`` result from registered plugins.  Method names are prefixed
    with ``ws_`` to namespace them within the pluggy project.
    """

    @hookspec(firstresult=True)
    def ws_detect_workflow_type(self, project_file: str) -> str | None: ...

    @hookspec(firstresult=True)
    def ws_get_change_label(self, project_file: str) -> str | None: ...

    @hookspec(firstresult=True)
    def ws_resolve_ref(self, ref: str, workflow_type: str) -> ResolvedRef | None: ...

    @hookspec(firstresult=True)
    def ws_submit(
        self,
        changespec_file: str,
        changespec_name: str,
        project_basename: str,
        console: object | None,
    ) -> tuple[bool, str | None] | None: ...

    @hookspec(firstresult=True)
    def ws_setup_workflow(
        self,
        ref: str,
        workflow_type: str,
        n: int,
        release: bool,
    ) -> dict[str, str] | None: ...
