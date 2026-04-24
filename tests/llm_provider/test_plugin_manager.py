"""Tests for LLMPluginManager delegation and fallback behaviour."""

import pluggy
import pytest

from sase.llm_provider._hookspec import LLMHookSpec, hookimpl
from sase.llm_provider._plugin_manager import LLMPluginManager
from sase.llm_provider.base import LLMProvider
from sase.llm_provider.types import InvokeResult, ModelTier


def _make_manager(*plugins: object) -> LLMPluginManager:
    """Create an LLMPluginManager with the given plugin objects registered."""
    pm = pluggy.PluginManager("sase_llm")
    pm.add_hookspecs(LLMHookSpec)
    for plugin in plugins:
        pm.register(plugin)
    return LLMPluginManager(pm)


# ---------------------------------------------------------------------------
# Minimal plugin fixtures
# ---------------------------------------------------------------------------


class _FullPlugin:
    """Plugin implementing all three core hooks."""

    @hookimpl
    def llm_invoke(
        self,
        prompt: str,
        model_tier: ModelTier,
        suppress_output: bool,
        model_override: str | None,
    ) -> InvokeResult:
        return InvokeResult(
            content=f"resp:{prompt}:{model_tier}:{suppress_output}:{model_override}"
        )

    @hookimpl
    def llm_resolve_model_name(self, model_tier: ModelTier) -> str:
        return f"fake-{model_tier}"

    @hookimpl
    def llm_provider_name(self) -> str:
        return "fake"


class _InvokeOnlyPlugin:
    """Plugin implementing only llm_invoke."""

    @hookimpl
    def llm_invoke(
        self,
        prompt: str,
        model_tier: ModelTier,
        suppress_output: bool,
        model_override: str | None,
    ) -> InvokeResult:
        return InvokeResult(content="ok")


# ---------------------------------------------------------------------------
# Tests: delegation to plugins
# ---------------------------------------------------------------------------


class TestDelegation:
    """LLMPluginManager should forward calls to registered plugins."""

    def test_invoke_delegates(self) -> None:
        mgr = _make_manager(_FullPlugin())
        result = mgr.invoke(
            "hello",
            model_tier="large",
            suppress_output=True,
            model_override="opus",
        )
        assert result == InvokeResult(content="resp:hello:large:True:opus")

    def test_invoke_passes_defaults(self) -> None:
        mgr = _make_manager(_InvokeOnlyPlugin())
        result = mgr.invoke("hi", model_tier="small")
        assert result == InvokeResult(content="ok")

    def test_resolve_model_name_delegates(self) -> None:
        mgr = _make_manager(_FullPlugin())
        assert mgr.resolve_model_name("large") == "fake-large"
        assert mgr.resolve_model_name("small") == "fake-small"

    def test_provider_name_delegates(self) -> None:
        mgr = _make_manager(_FullPlugin())
        assert mgr.provider_name() == "fake"


# ---------------------------------------------------------------------------
# Tests: NotImplementedError / defaults when no plugin handles the hook
# ---------------------------------------------------------------------------


class TestNoPlugin:
    """Behaviour when no plugin implements a hook."""

    def test_invoke_raises_when_unhandled(self) -> None:
        mgr = _make_manager()
        with pytest.raises(NotImplementedError, match="invoke"):
            mgr.invoke("hi", model_tier="large")

    def test_resolve_model_name_returns_unknown_by_default(self) -> None:
        mgr = _make_manager()
        assert mgr.resolve_model_name() == "unknown"

    def test_provider_name_raises_when_unhandled(self) -> None:
        mgr = _make_manager()
        with pytest.raises(NotImplementedError, match="provider_name"):
            mgr.provider_name()


# ---------------------------------------------------------------------------
# Tests: LLMProvider interface compliance
# ---------------------------------------------------------------------------


class TestInterfaceCompliance:
    """LLMPluginManager should be a valid LLMProvider subclass."""

    def test_is_llm_provider_subclass(self) -> None:
        assert issubclass(LLMPluginManager, LLMProvider)

    def test_instance_is_llm_provider(self) -> None:
        mgr = _make_manager()
        assert isinstance(mgr, LLMProvider)
