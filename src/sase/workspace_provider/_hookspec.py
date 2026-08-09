"""Pluggy hook specifications for workspace provider plugins."""

from dataclasses import dataclass, field
from typing import Literal

import pluggy

hookspec = pluggy.HookspecMarker("sase_workspace")
hookimpl = pluggy.HookimplMarker("sase_workspace")

SUBMITTED_CHECK_EXIT_CODE_CLOSED = 20

VcsRepoCandidateStatus = Literal["ok", "error"]
VcsRepoCandidateErrorKind = Literal[
    "auth",
    "network",
    "not_found",
    "tool_missing",
    "unsupported_namespace",
    "unknown",
]
SddSidecarPreflightStatus = Literal["found", "not_found", "unavailable"]


@dataclass(frozen=True)
class SddSidecarPreflight:
    """Read-only discovery result for a provider-owned SDD sidecar.

    ``visibility`` is the visibility the provider intends to use if the
    sidecar must be created. ``message`` carries an actionable explanation
    when ``status`` is ``"unavailable"``.
    """

    status: SddSidecarPreflightStatus
    provider: str
    host: str
    repo: str
    visibility: str
    message: str = ""


@dataclass
class ResolvedRef:
    """Result of resolving a workspace reference (e.g. ``#gh``, ``#git``).

    ``canonical_ref`` is the launch identity to use when the matched ref is a
    provider-specific locator rather than a stable project or Patch name.
    """

    project_file: str
    project_name: str
    primary_workspace_dir: str
    checkout_target: str
    extra: dict[str, str] = field(default_factory=dict)
    canonical_ref: str | None = None


@dataclass(frozen=True)
class ExternalRepoCloneResult:
    """Result of cloning one provider-owned repo into a workspace-local path."""

    canonical_name: str
    dest_dir: str
    default_branch: str


@dataclass(frozen=True)
class VcsRepoEntry:
    """One repository completion candidate returned by a workspace plugin.

    ``name`` is the repository's short name. ``ref`` is the full provider ref
    inserted into a prompt, usually ``namespace/name``.
    """

    name: str
    ref: str
    description: str = ""
    visibility: str = ""
    is_fork: bool = False
    is_archived: bool = False
    pushed_at: str | None = None


@dataclass(frozen=True)
class VcsRepoCandidates:
    """Repository completion response returned by workspace plugins."""

    status: VcsRepoCandidateStatus
    error_kind: VcsRepoCandidateErrorKind | None = None
    message: str = ""
    provider_display: str = ""
    entries: tuple[VcsRepoEntry, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class VcsNamespaceEntry:
    """One namespace candidate for a workflow ref root.

    Providers can use this for org/group-style refs that chain into repository
    completion, e.g. ``#gh:sase-org/``.
    """

    name: str
    description: str = ""
    kind_label: str = "org"


@dataclass(frozen=True)
class VcsRefNamespaces:
    """Namespace completion response returned by workspace plugins."""

    entries: tuple[VcsNamespaceEntry, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class WorkflowMetadata:
    """Metadata declared by a workspace plugin for its workflow type.

    Fields:
        workflow_type: Short name used in ``#type:ref`` prompts (e.g. ``"gh"``).
        ref_pattern: Regex string matching ``#type:ref`` or ``#type(ref)`` syntax.
        display_name: Human-readable name (e.g. ``"GitHub"``).
        pre_allocated_env_prefix: Env-var prefix for pre-allocated workspace
            variables (e.g. ``"SASE_GH"``).
        vcs_family: VCS family this workflow belongs to (e.g. ``"git"``,
            ``"hg"``).  Used by :func:`get_display_name_by_vcs_family`.
        vcs_provider_name: Specific VCS provider name returned by
            :func:`~sase.vcs_provider.detect_vcs` (e.g. ``"github"``,
            ``"bare_git"``, ``"hg"``).  Used by
            :func:`get_display_name_by_vcs`.
        sdd_storage_policy: Optional SDD storage policy declaration. Empty
            string means no opinion; providers may declare ``"in_tree"`` or
            ``"separate_repo"``.
        external_repo_schemes: Provider schemes accepted by
            :meth:`WorkspaceHookSpec.ws_clone_external_repo` (e.g. ``("gh",)``).
    """

    workflow_type: str
    ref_pattern: str
    display_name: str
    pre_allocated_env_prefix: str
    vcs_family: str = ""
    vcs_provider_name: str = ""
    sdd_storage_policy: str = ""
    external_repo_schemes: tuple[str, ...] = field(default_factory=tuple)


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
    def ws_clone_external_repo(
        self,
        scheme: str,
        ref: str,
        dest_dir: str,
    ) -> ExternalRepoCloneResult | None:
        """Clone *ref* for an owned scheme, or return ``None`` if unowned."""
        ...

    @hookspec(firstresult=True)
    def ws_peek_ref(self, ref: str, workflow_type: str) -> ResolvedRef | None:
        """Read-only workspace reference lookup.

        Implementations must not clone repositories, create project records,
        write files, spawn network subprocesses, or otherwise mutate local or
        remote state. Return ``None`` when the ref cannot be resolved from
        existing local state.
        """
        ...

    @hookspec(firstresult=True)
    def ws_list_repo_candidates(
        self, workflow_type: str, namespace: str
    ) -> VcsRepoCandidates | None:
        """List repository completion candidates for a VCS namespace."""
        ...

    @hookspec(firstresult=True)
    def ws_list_ref_namespaces(
        self,
        workflow_type: str,
    ) -> VcsRefNamespaces | None:
        """List org/group-style namespace candidates for a workflow ref root.

        This hook runs on an interactive completion path and must use only
        fast local data such as project records or config. Providers should
        return ``None`` unless they own *workflow_type*.
        """
        ...

    @hookspec(firstresult=True)
    def ws_submit(
        self,
        patch_file: str,
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
    def ws_materialize_sdd_store(
        self,
        primary_workspace_dir: str,
        workspace_dir: str,
        options: dict[str, object],
    ) -> dict[str, object] | None:
        """Materialize the provider-required external SDD store at setup time.

        ``options["staging_dir"]`` is a unique core-owned clone target.
        Providers should find or create the required remote, populate that
        target, and return a positive schema-versioned record mapping for
        ``.sase/sdd-store.json``. Return ``None`` only when the provider does
        not own the current workspace.
        """
        ...

    @hookspec(firstresult=True)
    def ws_preflight_sdd_sidecar(
        self,
        primary_workspace_dir: str,
        workspace_dir: str,
        options: dict[str, object],
    ) -> SddSidecarPreflight | None:
        """Discover the external SDD sidecar without mutating state.

        This explicit-init hook may perform authoritative network reads. It
        must not create or label repositories, clone, or write local state.
        ``options["sdd_sidecar_suffix"]`` may select an arbitrary sidecar
        suffix such as ``plans`` or ``research``; absent means legacy ``sdd``.
        ``options["sdd_repo"]`` may pin an exact provider repository, while
        ``options["sdd_visibility"]`` and ``options["sdd_description"]`` carry
        creation-time settings from the configured sidecar entry.
        Return ``None`` only when the provider does not own the workspace.
        """
        ...

    @hookspec(firstresult=True)
    def ws_create_sdd_remote(
        self,
        primary_workspace_dir: str,
        workspace_dir: str,
        options: dict[str, object],
    ) -> dict[str, object] | None:
        """Compatibility hook to verify or create a sidecar SDD remote.

        Providers should return a schema-versioned record mapping suitable for
        ``.sase/sdd-store.json``. Provider-owned materialization requires
        creation when the remote is missing. Existing materialized records may
        be passed back through ``options["sdd_repo"]``,
        ``options["sdd_host"]``, and ``options["sdd_remote_url"]`` so providers
        can verify the exact recorded remote.
        ``options["sdd_sidecar_suffix"]``, ``options["sdd_visibility"]``, and
        ``options["sdd_description"]`` follow the preflight contract.
        """
        ...

    @hookspec(firstresult=True)
    def ws_extract_change_identifier(self, pr_url: str) -> tuple[str, str] | None: ...

    @hookspec(firstresult=True)
    def ws_generate_submitted_check_script(
        self, identifier: str, vcs_type: str
    ) -> str | None:
        """Generate a shell fragment for checking whether a PR is submitted.

        The returned script body must not call ``exit`` directly because the
        scheduler wrapper captures the final ``$?``. Exit code ``0`` means the
        PR was submitted or merged,
        :data:`SUBMITTED_CHECK_EXIT_CODE_CLOSED` means it was closed without
        merging, and any other code means no status signal was available.
        """
        ...

    @hookspec(firstresult=True)
    def ws_supports_reviewer_comments(self, pr_url: str) -> bool | None: ...

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
    def ws_prepare_mail(
        self,
        changespec_name: str,
        patch_parent: str | None,
        project_basename: str,
        project_file: str,
        target_dir: str,
        console: object | None,
    ) -> object | None: ...

    @hookspec(firstresult=True)
    def ws_format_commit_description(
        self,
        file_path: str,
        project: str,
        workflow_type: str,
        bug: str | None,
        fixed_bug: str | None,
    ) -> bool | None: ...

    @hookspec(firstresult=True)
    def ws_get_workspace_name(self, cwd: str) -> str | None: ...
