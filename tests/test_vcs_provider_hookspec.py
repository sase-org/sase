"""Tests for VCS hookspec definitions."""

import inspect

import pluggy

from sase.vcs_provider._base import VCSProvider
from sase.vcs_provider._hookspec import VCSHookSpec, hookimpl, hookspec


# Every VCSProvider method should have a corresponding vcs_* hookspec method.
_PROVIDER_METHODS = [
    name
    for name, _ in inspect.getmembers(VCSProvider, predicate=inspect.isfunction)
    if not name.startswith("_")
]


class TestHookspecMethodsExist:
    """Verify that every public VCSProvider method has a hookspec counterpart."""

    def test_all_provider_methods_have_hookspecs(self) -> None:
        hookspec_methods = {
            name
            for name, _ in inspect.getmembers(VCSHookSpec, predicate=inspect.isfunction)
            if name.startswith("vcs_")
        }
        for method_name in _PROVIDER_METHODS:
            assert f"vcs_{method_name}" in hookspec_methods, (
                f"VCSProvider.{method_name} has no hookspec counterpart "
                f"VCSHookSpec.vcs_{method_name}"
            )

    def test_no_extra_hookspecs(self) -> None:
        """Hookspec methods should map 1-to-1 with provider methods.

        Classification hooks (like ``vcs_classify_repo``) are excluded
        because they operate at the registry level, not on a provider
        instance.
        """
        # Hooks used by the registry for provider discovery, not by
        # VCSProvider instances.
        _CLASSIFICATION_HOOKS = {"classify_repo"}

        hookspec_names = {
            name.removeprefix("vcs_")
            for name, _ in inspect.getmembers(VCSHookSpec, predicate=inspect.isfunction)
            if name.startswith("vcs_")
        }
        provider_names = set(_PROVIDER_METHODS)
        extra = hookspec_names - provider_names - _CLASSIFICATION_HOOKS
        assert not extra, (
            f"Extra hookspec methods with no provider counterpart: {extra}"
        )


class TestHookspecSignatures:
    """Verify hookspec parameter names match VCSProvider signatures."""

    def test_parameter_names_match(self) -> None:
        for method_name in _PROVIDER_METHODS:
            provider_sig = inspect.signature(getattr(VCSProvider, method_name))
            hookspec_sig = inspect.signature(getattr(VCSHookSpec, f"vcs_{method_name}"))

            # Strip 'self' from both
            provider_params = [p for p in provider_sig.parameters if p != "self"]
            hookspec_params = [p for p in hookspec_sig.parameters if p != "self"]

            assert provider_params == hookspec_params, (
                f"Parameter mismatch for {method_name}: "
                f"provider={provider_params}, hookspec={hookspec_params}"
            )


class TestHookspecMarkers:
    """Verify the marker objects are correctly configured."""

    def test_hookspec_marker(self) -> None:
        assert isinstance(hookspec, pluggy.HookspecMarker)

    def test_hookimpl_marker(self) -> None:
        assert isinstance(hookimpl, pluggy.HookimplMarker)

    def test_project_name(self) -> None:
        # Both markers should be for the same pluggy project
        assert hookspec.project_name == "sase_vcs"
        assert hookimpl.project_name == "sase_vcs"


class TestHookspecRegistration:
    """Verify hookspecs can be registered with a pluggy PluginManager."""

    def test_add_hookspecs(self) -> None:
        pm = pluggy.PluginManager("sase_vcs")
        pm.add_hookspecs(VCSHookSpec)
        # Should not raise — hookspecs are valid

    def test_hookspecs_are_firstresult(self) -> None:
        pm = pluggy.PluginManager("sase_vcs")
        pm.add_hookspecs(VCSHookSpec)

        for method_name in _PROVIDER_METHODS:
            hook = getattr(pm.hook, f"vcs_{method_name}")
            assert hook.spec is not None
            assert hook.spec.opts.get("firstresult") is True, (
                f"vcs_{method_name} should be firstresult=True"
            )
