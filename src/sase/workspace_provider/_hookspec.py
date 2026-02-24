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


@dataclass(frozen=True)
class WorkflowMetadata:
    """Metadata declared by a workspace plugin for its workflow type.

    Fields:
        workflow_type: Short name used in ``#type:ref`` prompts (e.g. ``"gh"``).
        ref_pattern: Regex string matching ``#type:ref`` or ``#type(ref)`` syntax.
        display_name: Human-readable name (e.g. ``"GitHub"``).
        pre_allocated_env_prefix: Env-var prefix for pre-allocated workspace
            variables (e.g. ``"SASE_GH"``).
    """

    workflow_type: str
    ref_pattern: str
    display_name: str
    pre_allocated_env_prefix: str


class WorkspaceHookSpec:
    """Hook specifications for workspace provider plugins.

    Every method uses ``firstresult=True`` so pluggy returns the first
    non-``None`` result from registered plugins, **except**
    ``ws_get_workflow_metadata`` which collects results from all plugins.
    Method names are prefixed with ``ws_`` to namespace them within the
    pluggy project.
    """

    @hookspec
    def ws_get_workflow_metadata(self) -> WorkflowMetadata | None: ...

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

    @hookspec(firstresult=True)
    def ws_extract_change_identifier(self, cl_url: str) -> tuple[str, str] | None: ...

    @hookspec(firstresult=True)
    def ws_generate_submitted_check_script(
        self, identifier: str, vcs_type: str
    ) -> str | None: ...

    @hookspec(firstresult=True)
    def ws_supports_reviewer_comments(self, cl_url: str) -> bool | None: ...

    @hookspec(firstresult=True)
    def ws_generate_reviewer_comments_script(
        self, changespec_name: str
    ) -> str | None: ...

    @hookspec(firstresult=True)
    def ws_get_workspace_directory(
        self,
        workflow_type: str,
        workspace_num: int,
        project_name: str,
        primary_workspace_dir: str,
    ) -> str | None: ...

    @hookspec(firstresult=True)
    def ws_format_commit_description(
        self,
        file_path: str,
        project: str,
        workflow_type: str,
        bug: str | None,
        fixed_bug: str | None,
    ) -> bool | None: ...
