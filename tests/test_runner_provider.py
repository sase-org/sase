"""Tests for runner provider protocol, discovery, and directive parsing."""

from unittest.mock import MagicMock, patch

import pytest

from sase.runner_provider import (
    PostAgentResult,
    RunnerContext,
    RunnerProvider,
    get_runner_provider_names,
    get_runner_providers,
)
from sase.xprompt._exceptions import DirectiveError
from sase.xprompt.directives import extract_prompt_directives


# ---------------------------------------------------------------------------
# RunnerProvider ABC tests
# ---------------------------------------------------------------------------


class ConcreteProvider(RunnerProvider):
    """Minimal concrete implementation for testing."""

    @property
    def name(self) -> str:
        return "test"

    def pre_agent(
        self,
        ref: str,
        *,
        n: int | None = None,
        release: bool = True,
    ) -> RunnerContext:
        return RunnerContext(checkout_target=ref, should_release=release)

    def post_agent(self, ctx: RunnerContext) -> PostAgentResult:
        return PostAgentResult(diff_path="/tmp/test.diff")


class TestRunnerProviderABC:
    """Tests for the RunnerProvider abstract base class."""

    def test_concrete_subclass_works(self) -> None:
        provider = ConcreteProvider()
        assert provider.name == "test"
        ctx = provider.pre_agent("main")
        assert ctx.checkout_target == "main"
        assert ctx.should_release is True
        result = provider.post_agent(ctx)
        assert result.diff_path == "/tmp/test.diff"

    def test_abstract_instantiation_raises(self) -> None:
        with pytest.raises(TypeError):
            RunnerProvider()  # type: ignore[abstract]


# ---------------------------------------------------------------------------
# Entry point discovery tests
# ---------------------------------------------------------------------------


def _make_entry_point(name: str, provider_class: type) -> MagicMock:
    """Create a mock entry point that loads *provider_class*."""
    ep = MagicMock()
    ep.name = name
    ep.load.return_value = provider_class
    return ep


class TestGetRunnerProviders:
    """Tests for get_runner_providers() entry point discovery."""

    def test_discovers_mock_entry_points(self) -> None:
        ep = _make_entry_point("test", ConcreteProvider)
        with patch(
            "sase.runner_provider.importlib.metadata.entry_points",
            return_value=[ep],
        ):
            providers = get_runner_providers()
        assert "test" in providers
        assert isinstance(providers["test"], ConcreteProvider)

    def test_skips_failed_entry_points(self) -> None:
        bad_ep = MagicMock()
        bad_ep.name = "broken"
        bad_ep.load.side_effect = ImportError("missing dependency")
        with (
            patch(
                "sase.runner_provider.importlib.metadata.entry_points",
                return_value=[bad_ep],
            ),
            patch(
                "sase.runner_providers.git.GitRunnerProvider",
                side_effect=ImportError,
            ),
        ):
            providers = get_runner_providers()
        assert providers == {}

    def test_empty_when_no_entry_points_and_no_builtin(self) -> None:
        with (
            patch(
                "sase.runner_provider.importlib.metadata.entry_points",
                return_value=[],
            ),
            patch(
                "sase.runner_providers.git.GitRunnerProvider",
                side_effect=ImportError,
            ),
        ):
            providers = get_runner_providers()
        assert providers == {}


class TestGetRunnerProviderNames:
    """Tests for get_runner_provider_names()."""

    def test_returns_frozenset_of_names(self) -> None:
        ep = _make_entry_point("test", ConcreteProvider)
        with patch(
            "sase.runner_provider.importlib.metadata.entry_points",
            return_value=[ep],
        ):
            names = get_runner_provider_names()
        # Includes both the built-in "git" and the mock "test" entry point
        assert names == frozenset({"test", "git"})


# ---------------------------------------------------------------------------
# Directive parsing tests for runner directives
# ---------------------------------------------------------------------------


class TestRunnerDirectiveParsing:
    """Tests for runner directive parsing in extract_prompt_directives()."""

    def test_colon_syntax(self) -> None:
        prompt = "%git:sase Review this code"
        cleaned, directives = extract_prompt_directives(
            prompt, runner_provider_names=frozenset({"git", "gh"})
        )
        assert directives.runner == ("git", "sase", {})
        assert "Review this code" in cleaned
        assert "%git:sase" not in cleaned

    def test_paren_syntax_with_ref_and_named_args(self) -> None:
        prompt = "%gh(org/repo, n=3) Do stuff"
        cleaned, directives = extract_prompt_directives(
            prompt, runner_provider_names=frozenset({"git", "gh"})
        )
        assert directives.runner is not None
        name, ref, named = directives.runner
        assert name == "gh"
        assert ref == "org/repo"
        assert named == {"n": "3"}
        assert "%gh" not in cleaned

    def test_paren_syntax_with_named_args_only(self) -> None:
        prompt = "%git(sase, release=false) Work on it"
        cleaned, directives = extract_prompt_directives(
            prompt, runner_provider_names=frozenset({"git"})
        )
        assert directives.runner is not None
        name, ref, named = directives.runner
        assert name == "git"
        assert ref == "sase"
        assert named == {"release": "false"}

    def test_multiple_runner_directives_raises(self) -> None:
        prompt = "%git:sase %gh:org/repo Do stuff"
        with pytest.raises(DirectiveError, match="Multiple runner directives"):
            extract_prompt_directives(
                prompt, runner_provider_names=frozenset({"git", "gh"})
            )

    def test_runner_combined_with_model_directive(self) -> None:
        prompt = "%model:opus %git:sase Review code"
        cleaned, directives = extract_prompt_directives(
            prompt, runner_provider_names=frozenset({"git"})
        )
        assert directives.model == "opus"
        assert directives.runner == ("git", "sase", {})
        assert "%model" not in cleaned
        assert "%git" not in cleaned

    def test_unknown_provider_left_in_prompt(self) -> None:
        prompt = "%unknown:foo Review this"
        cleaned, directives = extract_prompt_directives(
            prompt, runner_provider_names=frozenset({"git"})
        )
        assert directives.runner is None
        assert "%unknown:foo" in cleaned

    def test_default_no_runner_provider_names_ignores(self) -> None:
        prompt = "%git:sase Review this"
        cleaned, directives = extract_prompt_directives(prompt)
        assert directives.runner is None
        assert "%git:sase" in cleaned
