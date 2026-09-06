"""Tests for Jinja2 context rendering in preprocess_prompt_early."""

from unittest.mock import patch

import pytest

from sase.llm_provider.preprocessing import preprocess_prompt_early
from sase.xprompt.runtime_context import bind_runtime_template_vars


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

    @patch("sase.xprompt.process_xprompt_references", side_effect=lambda x, **kw: x)
    def test_wait_chats_rendered(self, _mock_xprompt: object) -> None:
        """{{ wait_chats | join(',') }} renders when context has wait_chats."""
        result = preprocess_prompt_early(
            "Transcripts: {{ wait_chats | join(',') }}",
            context={"wait_chats": ["~/.sase/chats/a.md", "~/.sase/chats/b.md"]},
        )
        assert "Transcripts: ~/.sase/chats/a.md,~/.sase/chats/b.md" in result.prompt

    @patch("sase.xprompt.process_xprompt_references", side_effect=lambda x, **kw: x)
    def test_wait_namespace_rendered_from_runtime_context(
        self,
        _mock_xprompt: object,
    ) -> None:
        """{{ wait.chats }} renders from the scoped runtime namespace."""

        class Wait:
            chats = ["~/.sase/chats/a.md"]

        with bind_runtime_template_vars({"wait": Wait()}):
            result = preprocess_prompt_early(
                "Transcripts: {{ wait.chats | join(',') }}",
                context={},
            )

        assert "Transcripts: ~/.sase/chats/a.md" in result.prompt

    @patch("sase.xprompt.process_xprompt_references", side_effect=lambda x, **kw: x)
    def test_context_input_overrides_runtime_wait_namespace(
        self,
        _mock_xprompt: object,
    ) -> None:
        """Declared context values retain precedence over runtime globals."""

        class Wait:
            chats = ["runtime"]

        with bind_runtime_template_vars({"wait": Wait()}):
            result = preprocess_prompt_early(
                "Wait: {{ wait }}",
                context={"wait": "input"},
            )

        assert "Wait: input" in result.prompt

    @patch("sase.xprompt.process_xprompt_references", side_effect=lambda x, **kw: x)
    def test_unknown_wait_member_raises_at_runtime(
        self,
        _mock_xprompt: object,
    ) -> None:
        """Unknown wait members retain StrictUndefined runtime behavior."""

        class Wait:
            chats: list[str] = []

        with bind_runtime_template_vars({"wait": Wait()}):
            with pytest.raises(Exception, match="no attribute 'missing'"):
                preprocess_prompt_early("{{ wait.missing }}", context={})

    @patch("sase.xprompt.process_xprompt_references", side_effect=lambda x, **kw: x)
    def test_wait_chats_not_in_context_raises(self, _mock_xprompt: object) -> None:
        """{{ wait_chats }} without wait_chats in context raises UndefinedError."""
        from jinja2 import UndefinedError

        import pytest

        with pytest.raises(UndefinedError):
            preprocess_prompt_early(
                "{{ wait_chats }}",
                context={"cl_name": "test"},
            )

    @patch("sase.xprompt.process_xprompt_references", side_effect=lambda x, **kw: x)
    def test_disabled_region_preserves_new_multi_model_syntax(
        self,
        _mock_xprompt: object,
    ) -> None:
        """Disabled regions can contain Jinja-looking multi-model syntax."""
        prompt = (
            "before\n"
            "%xprompts_enabled:false\n"
            "%{%m:claude/opus | %m:codex/gpt-5.6-sol}\n"
            "%xprompts_enabled:true\n"
            "after\n"
        )

        result = preprocess_prompt_early(prompt, context={"N": 1})

        assert "%{%m:claude/opus | %m:codex/gpt-5.6-sol}" in result.prompt

    @patch("sase.xprompt.process_xprompt_references", side_effect=lambda x, **kw: x)
    def test_disabled_region_jinja_content_is_opaque(
        self,
        _mock_xprompt: object,
    ) -> None:
        """Jinja syntax inside disabled regions is not parsed or rendered."""
        prompt = (
            "%xprompts_enabled:false\n"
            "{% for value in missing_values %}{{ value }}{% endfor %}\n"
            "%xprompts_enabled:true\n"
        )

        result = preprocess_prompt_early(prompt, context={"N": 1})

        assert "{% for value in missing_values %}" in result.prompt
        assert "{{ value }}" in result.prompt
        assert "{% endfor %}" in result.prompt

    @patch("sase.xprompt.process_xprompt_references", side_effect=lambda x, **kw: x)
    def test_disabled_region_does_not_block_outside_jinja_rendering(
        self,
        _mock_xprompt: object,
    ) -> None:
        """Only disabled-region Jinja is masked; outside Jinja still renders."""
        prompt = (
            "Run {{ N }}\n"
            "%xprompts_enabled:false\n"
            "Keep {{ N }} literal.\n"
            "%xprompts_enabled:true\n"
        )

        result = preprocess_prompt_early(prompt, context={"N": 7})

        assert "Run 7" in result.prompt
        assert "Keep {{ N }} literal." in result.prompt

    @patch("sase.xprompt.process_xprompt_references", side_effect=lambda x, **kw: x)
    def test_disabled_region_markers_survive_early_jinja_rendering(
        self,
        _mock_xprompt: object,
    ) -> None:
        """Early preprocessing preserves markers for the late phase."""
        prompt = (
            "%xprompts_enabled:false\n"
            "{{ not_rendered }}\n"
            "%xprompts_enabled:true\n"
            "{{ rendered }}\n"
        )

        result = preprocess_prompt_early(prompt, context={"rendered": "done"})

        assert "%xprompts_enabled:false" in result.prompt
        assert "%xprompts_enabled:true" in result.prompt
        assert "{{ not_rendered }}" in result.prompt
        assert "done" in result.prompt
