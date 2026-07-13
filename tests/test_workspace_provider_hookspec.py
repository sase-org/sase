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
