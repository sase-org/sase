"""Tests for workspace provider hookspec definitions."""

import inspect
from pathlib import Path

import pluggy
import pytest

from sase.workspace_provider._hookspec import (
    ExternalRepoCloneResult,
    WorkflowMetadata,
    WorkspaceHookSpec,
    hookimpl,
    hookspec,
)
from sase.workspace_provider._plugin_manager import WorkspacePluginManager


# Every WorkspacePluginManager method should have a corresponding ws_* hookspec.
_MANAGER_METHODS = [
    name
    for name, _ in inspect.getmembers(
        WorkspacePluginManager, predicate=inspect.isfunction
    )
    if not name.startswith("_")
]


class TestHookspecMethodsExist:
    """Verify that every WorkspacePluginManager method has a hookspec counterpart."""

    def test_all_manager_methods_have_hookspecs(self) -> None:
        hookspec_methods = {
            name
            for name, _ in inspect.getmembers(
                WorkspaceHookSpec, predicate=inspect.isfunction
            )
            if name.startswith("ws_")
        }
        for method_name in _MANAGER_METHODS:
            assert f"ws_{method_name}" in hookspec_methods, (
                f"WorkspacePluginManager.{method_name} has no hookspec "
                f"counterpart WorkspaceHookSpec.ws_{method_name}"
            )

    def test_no_extra_hookspecs(self) -> None:
        """Hookspec methods should map 1-to-1 with manager methods."""
        hookspec_names = {
            name.removeprefix("ws_")
            for name, _ in inspect.getmembers(
                WorkspaceHookSpec, predicate=inspect.isfunction
            )
            if name.startswith("ws_")
        }
        manager_names = set(_MANAGER_METHODS)
        extra = hookspec_names - manager_names
        assert not extra, f"Extra hookspec methods with no manager counterpart: {extra}"


class TestHookspecSignatures:
    """Verify hookspec parameter names match WorkspacePluginManager signatures."""

    def test_parameter_names_match(self) -> None:
        for method_name in _MANAGER_METHODS:
            manager_sig = inspect.signature(
                getattr(WorkspacePluginManager, method_name)
            )
            hookspec_sig = inspect.signature(
                getattr(WorkspaceHookSpec, f"ws_{method_name}")
            )

            # Strip 'self' from both
            manager_params = [p for p in manager_sig.parameters if p != "self"]
            hookspec_params = [p for p in hookspec_sig.parameters if p != "self"]

            assert manager_params == hookspec_params, (
                f"Parameter mismatch for {method_name}: "
                f"manager={manager_params}, hookspec={hookspec_params}"
            )


# Hookspec argument names are a cross-repo compatibility boundary: pluggy
# matches hookimpl parameters to hookspec parameters by name and raises
# PluginValidationError at registration time for any hookimpl argument missing
# from the spec. Renaming or removing a name here therefore crashes every
# out-of-tree plugin built against the old name (sase-github, sase-telegram,
# ...) as soon as it registers -- which is how a Patch-terminology sweep once
# broke `sase ace` at startup by renaming ws_submit's `changespec_file` and
# ws_prepare_mail's `changespec_parent`.
#
# Adding an argument is safe and needs no update here; renaming or removing one
# is a breaking plugin-API change that must be coordinated with every plugin
# repo before this pin is edited. Legacy `changespec_*` spellings stay frozen
# regardless of internal Patch terminology -- adapt to Patch locals inside the
# implementation instead.
_FROZEN_HOOK_ARGUMENTS: dict[str, tuple[str, ...]] = {
    "ws_clone_external_repo": ("scheme", "ref", "dest_dir"),
    "ws_create_sdd_remote": ("primary_workspace_dir", "workspace_dir", "options"),
    "ws_detect_workflow_type": ("project_file",),
    "ws_extract_change_identifier": ("pr_url",),
    "ws_format_commit_description": (
        "file_path",
        "project",
        "workflow_type",
        "bug",
        "fixed_bug",
    ),
    "ws_generate_reviewer_comments_script": ("changespec_name",),
    "ws_generate_submitted_check_script": ("identifier", "vcs_type"),
    "ws_get_change_label": ("project_file",),
    "ws_get_workflow_metadata": (),
    "ws_get_workspace_directory": (
        "workflow_type",
        "workspace_num",
        "project_name",
        "primary_workspace_dir",
    ),
    "ws_get_workspace_name": ("cwd",),
    "ws_list_ref_namespaces": ("workflow_type",),
    "ws_list_repo_candidates": ("workflow_type", "namespace"),
    "ws_materialize_sdd_store": ("primary_workspace_dir", "workspace_dir", "options"),
    "ws_peek_ref": ("ref", "workflow_type"),
    "ws_preflight_sdd_sidecar": ("primary_workspace_dir", "workspace_dir", "options"),
    "ws_prepare_mail": (
        "changespec_name",
        "changespec_parent",
        "project_basename",
        "project_file",
        "target_dir",
        "console",
    ),
    "ws_resolve_ref": ("ref", "workflow_type"),
    "ws_setup_workflow": ("ref", "workflow_type", "n", "release"),
    "ws_submit": (
        "changespec_file",
        "changespec_name",
        "project_basename",
        "console",
    ),
    "ws_supports_reviewer_comments": ("pr_url",),
}


class TestFrozenHookArgumentNames:
    """Guard the hookspec argument names out-of-tree plugins bind to."""

    def test_every_hookspec_is_pinned(self) -> None:
        declared = {
            name
            for name, _ in inspect.getmembers(
                WorkspaceHookSpec, predicate=inspect.isfunction
            )
            if name.startswith("ws_")
        }
        unpinned = declared - set(_FROZEN_HOOK_ARGUMENTS)
        assert not unpinned, (
            f"New hookspec(s) {sorted(unpinned)} are not pinned in "
            "_FROZEN_HOOK_ARGUMENTS. Add their argument names so a later rename "
            "cannot silently break out-of-tree plugins."
        )

    @pytest.mark.parametrize("hook_name", sorted(_FROZEN_HOOK_ARGUMENTS))
    def test_frozen_arguments_are_still_declared(self, hook_name: str) -> None:
        hook = getattr(WorkspaceHookSpec, hook_name, None)
        assert hook is not None, (
            f"Hookspec {hook_name} was removed. Every out-of-tree plugin that "
            "implements it will stop being called; coordinate the removal with "
            "the plugin repos before editing _FROZEN_HOOK_ARGUMENTS."
        )

        current = {p for p in inspect.signature(hook).parameters if p != "self"}
        missing = set(_FROZEN_HOOK_ARGUMENTS[hook_name]) - current

        assert not missing, (
            f"Hookspec {hook_name} no longer declares {sorted(missing)}.\n"
            "Hookspec argument names are a plugin API boundary: pluggy raises "
            "PluginValidationError at registration time for any hookimpl "
            "argument missing from the spec, so every out-of-tree plugin using "
            f"the old name crashes at startup (current names: {sorted(current)}).\n"
            "Legacy `changespec_*` argument names stay frozen even where "
            "internal code uses Patch terminology -- rename to a Patch local "
            "inside the implementation instead."
        )


class TestHookspecMarkers:
    """Verify the marker objects are correctly configured."""

    def test_hookspec_marker(self) -> None:
        assert isinstance(hookspec, pluggy.HookspecMarker)

    def test_hookimpl_marker(self) -> None:
        assert isinstance(hookimpl, pluggy.HookimplMarker)

    def test_project_name(self) -> None:
        assert hookspec.project_name == "sase_workspace"
        assert hookimpl.project_name == "sase_workspace"


class TestHookspecRegistration:
    """Verify hookspecs can be registered with a pluggy PluginManager."""

    def test_add_hookspecs(self) -> None:
        pm = pluggy.PluginManager("sase_workspace")
        pm.add_hookspecs(WorkspaceHookSpec)

    def test_hookspecs_are_firstresult(self) -> None:
        pm = pluggy.PluginManager("sase_workspace")
        pm.add_hookspecs(WorkspaceHookSpec)

        # ws_get_workflow_metadata intentionally collects from ALL plugins
        _NOT_FIRSTRESULT = {"get_workflow_metadata"}

        for method_name in _MANAGER_METHODS:
            hook = getattr(pm.hook, f"ws_{method_name}")
            assert hook.spec is not None
            if method_name in _NOT_FIRSTRESULT:
                assert hook.spec.opts.get("firstresult") is not True, (
                    f"ws_{method_name} should NOT be firstresult=True"
                )
            else:
                assert hook.spec.opts.get("firstresult") is True, (
                    f"ws_{method_name} should be firstresult=True"
                )


def test_out_of_tree_plugin_with_legacy_argument_names_registers() -> None:
    """Registration must accept the argument names shipped plugins bind to.

    Mirrors ``sase_github.workspace_plugin.GitHubWorkspacePlugin``, whose
    hookimpls declare the legacy ``changespec_file``/``changespec_parent``
    spellings. Renaming those in the hookspec made pluggy raise
    ``PluginValidationError`` here, which crashed ``sase ace`` at startup.
    """

    class LegacyNamedPlugin:
        @hookimpl
        def ws_submit(
            self,
            changespec_file: str,
            changespec_name: str,
            project_basename: str,
            console: object | None = None,
        ) -> tuple[bool, str | None] | None:
            return (True, changespec_file)

        @hookimpl
        def ws_prepare_mail(
            self,
            changespec_name: str,
            changespec_parent: str | None,
            project_basename: str,
            project_file: str,
            target_dir: str,
            console: object | None,
        ) -> object | None:
            return changespec_parent

    pm = pluggy.PluginManager("sase_workspace")
    pm.add_hookspecs(WorkspaceHookSpec)
    pm.register(LegacyNamedPlugin())
    manager = WorkspacePluginManager(pm)

    assert manager.submit("patch.sase", "Feature", "proj") == (True, "patch.sase")
    assert (
        manager.prepare_mail("Feature", "Parent", "proj", "proj.sase", "/tmp", None)
        == "Parent"
    )


def test_external_repo_clone_dispatches_to_owning_plugin(tmp_path: Path) -> None:
    class ExternalPlugin:
        @hookimpl
        def ws_clone_external_repo(
            self,
            scheme: str,
            ref: str,
            dest_dir: str,
        ) -> ExternalRepoCloneResult | None:
            if scheme != "gh":
                return None
            return ExternalRepoCloneResult(
                canonical_name=f"gh:{ref}",
                dest_dir=dest_dir,
                default_branch="main",
            )

    pm = pluggy.PluginManager("sase_workspace")
    pm.add_hookspecs(WorkspaceHookSpec)
    pm.register(ExternalPlugin())
    manager = WorkspacePluginManager(pm)
    dest = str(tmp_path / "clone")

    assert manager.clone_external_repo("gl", "acme/widget", dest) is None
    assert manager.clone_external_repo("gh", "acme/widget", dest) == (
        ExternalRepoCloneResult(
            canonical_name="gh:acme/widget",
            dest_dir=dest,
            default_branch="main",
        )
    )


def test_external_repo_scheme_discovery_uses_plugin_metadata(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sase.workspace_provider import _registry

    monkeypatch.setattr(
        _registry,
        "get_all_workflow_metadata",
        lambda: (
            WorkflowMetadata(
                workflow_type="gh",
                ref_pattern=r"^#gh",
                display_name="GitHub",
                pre_allocated_env_prefix="SASE_GH",
                external_repo_schemes=("GH", " gh "),
            ),
            WorkflowMetadata(
                workflow_type="git",
                ref_pattern=r"^#git",
                display_name="Git",
                pre_allocated_env_prefix="SASE_GIT",
            ),
        ),
    )

    assert _registry.get_external_repo_schemes() == {"gh"}
