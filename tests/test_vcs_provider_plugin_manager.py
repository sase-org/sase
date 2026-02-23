"""Tests for VCSPluginManager delegation and fallback behaviour."""

import pluggy
import pytest

from sase.vcs_provider._hookspec import VCSHookSpec, hookimpl
from sase.vcs_provider._plugin_manager import VCSPluginManager


def _make_manager(*plugins: object) -> VCSPluginManager:
    """Create a VCSPluginManager with the given plugin objects registered."""
    pm = pluggy.PluginManager("sase_vcs")
    pm.add_hookspecs(VCSHookSpec)
    for plugin in plugins:
        pm.register(plugin)
    return VCSPluginManager(pm)


# ---------------------------------------------------------------------------
# Minimal plugin fixtures
# ---------------------------------------------------------------------------


class _CheckoutPlugin:
    """Plugin implementing only vcs_checkout."""

    @hookimpl
    def vcs_checkout(self, revision: str, cwd: str) -> tuple[bool, str | None]:
        return (True, None)


class _ResolveRevisionPlugin:
    """Plugin implementing vcs_resolve_revision."""

    @hookimpl
    def vcs_resolve_revision(
        self, changespec_name: str, project_basename: str, cwd: str
    ) -> str:
        return f"resolved-{changespec_name}"


class _PrepareDescriptionPlugin:
    """Plugin implementing vcs_prepare_description_for_reword."""

    @hookimpl
    def vcs_prepare_description_for_reword(self, description: str) -> str:
        return description.upper()


class _MultiMethodPlugin:
    """Plugin implementing several hooks."""

    @hookimpl
    def vcs_checkout(self, revision: str, cwd: str) -> tuple[bool, str | None]:
        return (True, None)

    @hookimpl
    def vcs_diff(self, cwd: str) -> tuple[bool, str | None]:
        return (True, "some diff")

    @hookimpl
    def vcs_add_remove(self, cwd: str) -> tuple[bool, str | None]:
        return (True, None)

    @hookimpl
    def vcs_is_sync_in_progress(self, cwd: str) -> bool:
        return False

    @hookimpl
    def vcs_get_conflicted_files(self, cwd: str) -> list[str]:
        return ["file.txt"]

    @hookimpl
    def vcs_get_default_parent_revision(self, cwd: str) -> str:
        return "origin/main"


# ---------------------------------------------------------------------------
# Tests: delegation to plugins
# ---------------------------------------------------------------------------


class TestDelegation:
    """VCSPluginManager should forward calls to registered plugins."""

    def test_checkout_delegates(self) -> None:
        mgr = _make_manager(_CheckoutPlugin())
        assert mgr.checkout("main", "/tmp") == (True, None)

    def test_diff_delegates(self) -> None:
        mgr = _make_manager(_MultiMethodPlugin())
        assert mgr.diff("/tmp") == (True, "some diff")

    def test_add_remove_delegates(self) -> None:
        mgr = _make_manager(_MultiMethodPlugin())
        assert mgr.add_remove("/tmp") == (True, None)

    def test_is_sync_in_progress_delegates(self) -> None:
        mgr = _make_manager(_MultiMethodPlugin())
        assert mgr.is_sync_in_progress("/tmp") is False

    def test_get_conflicted_files_delegates(self) -> None:
        mgr = _make_manager(_MultiMethodPlugin())
        assert mgr.get_conflicted_files("/tmp") == ["file.txt"]

    def test_get_default_parent_revision_delegates(self) -> None:
        mgr = _make_manager(_MultiMethodPlugin())
        assert mgr.get_default_parent_revision("/tmp") == "origin/main"


# ---------------------------------------------------------------------------
# Tests: NotImplementedError when no plugin handles the hook
# ---------------------------------------------------------------------------


class TestNotImplemented:
    """When no plugin implements a hook, NotImplementedError is raised."""

    def test_unimplemented_core_method_raises(self) -> None:
        mgr = _make_manager()  # no plugins at all
        with pytest.raises(NotImplementedError, match="checkout"):
            mgr.checkout("main", "/tmp")

    def test_unimplemented_optional_method_raises(self) -> None:
        mgr = _make_manager()
        with pytest.raises(NotImplementedError, match="show_revision"):
            mgr.show_revision("abc", "/tmp")

    def test_unimplemented_sync_workspace_raises(self) -> None:
        mgr = _make_manager()
        with pytest.raises(NotImplementedError, match="sync_workspace"):
            mgr.sync_workspace("/tmp")

    def test_unimplemented_is_sync_in_progress_raises(self) -> None:
        mgr = _make_manager()
        with pytest.raises(NotImplementedError, match="is_sync_in_progress"):
            mgr.is_sync_in_progress("/tmp")

    def test_unimplemented_get_conflicted_files_raises(self) -> None:
        mgr = _make_manager()
        with pytest.raises(NotImplementedError, match="get_conflicted_files"):
            mgr.get_conflicted_files("/tmp")

    def test_unimplemented_get_default_parent_revision_raises(self) -> None:
        mgr = _make_manager()
        with pytest.raises(NotImplementedError, match="get_default_parent_revision"):
            mgr.get_default_parent_revision("/tmp")

    def test_unimplemented_google_internal_raises(self) -> None:
        mgr = _make_manager()
        with pytest.raises(NotImplementedError, match="reword"):
            mgr.reword("desc", "/tmp")

    def test_partial_plugin_raises_for_unimplemented(self) -> None:
        """Plugin implements checkout but not diff => diff raises."""
        mgr = _make_manager(_CheckoutPlugin())
        assert mgr.checkout("main", "/tmp") == (True, None)
        with pytest.raises(NotImplementedError, match="diff"):
            mgr.diff("/tmp")


# ---------------------------------------------------------------------------
# Tests: non-trivial defaults
# ---------------------------------------------------------------------------


class TestNonTrivialDefaults:
    """Methods with non-trivial defaults should return them when no plugin handles."""

    def test_resolve_revision_returns_input_when_unhandled(self) -> None:
        mgr = _make_manager()  # no plugins
        assert mgr.resolve_revision("my-branch", "proj", "/tmp") == "my-branch"

    def test_resolve_revision_delegates_when_handled(self) -> None:
        mgr = _make_manager(_ResolveRevisionPlugin())
        assert mgr.resolve_revision("my-branch", "proj", "/tmp") == "resolved-my-branch"

    def test_prepare_description_returns_input_when_unhandled(self) -> None:
        mgr = _make_manager()
        assert mgr.prepare_description_for_reword("hello") == "hello"

    def test_prepare_description_delegates_when_handled(self) -> None:
        mgr = _make_manager(_PrepareDescriptionPlugin())
        assert mgr.prepare_description_for_reword("hello") == "HELLO"


# ---------------------------------------------------------------------------
# Tests: VCSProvider interface compliance
# ---------------------------------------------------------------------------


class TestInterfaceCompliance:
    """VCSPluginManager should be a valid VCSProvider subclass."""

    def test_is_subclass(self) -> None:
        assert issubclass(VCSPluginManager, type(mgr := _make_manager()).__mro__[0])
        from sase.vcs_provider._base import VCSProvider

        assert isinstance(mgr, VCSProvider)
