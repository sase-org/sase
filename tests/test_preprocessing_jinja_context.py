"""Tests for Jinja2 context rendering in preprocess_prompt_early."""

from unittest.mock import patch

from sase.llm_provider.preprocessing import preprocess_prompt_early


class TestJinjaContextRendering:
    """Verify that context dict variables are available in Jinja2 templates."""

    @patch("sase.xprompt.process_xprompt_references", side_effect=lambda x, **kw: x)
    def test_n_variable_rendered(self, _mock_xprompt: object) -> None:
        """{{ N }} renders to the iteration number when context has N."""
        result = preprocess_prompt_early(
            "Iteration {{ N }} of work",
            context={"N": 3},
        )
        assert "Iteration 3 of work" in result.prompt

    @patch("sase.xprompt.process_xprompt_references", side_effect=lambda x, **kw: x)
    def test_n_variable_first_iteration(self, _mock_xprompt: object) -> None:
        """{{ N }} renders to 1 for the first iteration."""
        result = preprocess_prompt_early(
            "Run {{ N }}",
            context={"N": 1},
        )
        assert "Run 1" in result.prompt

    @patch("sase.xprompt.process_xprompt_references", side_effect=lambda x, **kw: x)
    def test_n_not_in_context_raises(self, _mock_xprompt: object) -> None:
        """{{ N }} without N in context raises UndefinedError."""
        from jinja2 import UndefinedError

        import pytest

        with pytest.raises(UndefinedError):
            preprocess_prompt_early(
                "Iteration {{ N }}",
                context={"cl_name": "test"},
            )
