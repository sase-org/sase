"""Tests for expand_prompt_for_spec() and dry_expand_embedded_workflows()."""

from dataclasses import dataclass, field
from unittest.mock import patch

import pytest

from sase.sdd.files import dry_expand_embedded_workflows, expand_prompt_for_spec
from sase.xprompt.models import UNSET, InputArg


# ---------------------------------------------------------------------------
# Helpers: minimal Workflow stub for dry_expand_embedded_workflows tests
# ---------------------------------------------------------------------------


@dataclass
class _FakeStep:
    name: str = "prompt"
    prompt_part: str | None = None

    def is_prompt_part_step(self) -> bool:
        return self.prompt_part is not None


@dataclass
class _FakeWorkflow:
    name: str = "test"
    inputs: list[InputArg] = field(default_factory=list)
    steps: list[_FakeStep] = field(default_factory=list)

    def has_prompt_part(self) -> bool:
        return any(s.is_prompt_part_step() for s in self.steps)

    def get_prompt_part_content(self) -> str:
        for s in self.steps:
            if s.is_prompt_part_step():
                return s.prompt_part or ""
        return ""


def _make_workflow(
    name: str,
    prompt_part: str,
    inputs: list[InputArg] | None = None,
) -> _FakeWorkflow:
    return _FakeWorkflow(
        name=name,
        inputs=inputs or [],
        steps=[_FakeStep(name="prompt", prompt_part=prompt_part)],
    )


def _make_standalone_workflow(name: str) -> _FakeWorkflow:
    """Workflow with no prompt_part (standalone — should be left as-is)."""
    return _FakeWorkflow(
        name=name,
        inputs=[],
        steps=[_FakeStep(name="bash", prompt_part=None)],
    )


# ---------------------------------------------------------------------------
# dry_expand_embedded_workflows
# ---------------------------------------------------------------------------

_LOADER_PATH = "sase.xprompt.loader.get_all_workflows"


def test_dry_expand_no_workflows() -> None:
    """Plain text with no workflow references is unchanged."""
    with patch(_LOADER_PATH, return_value={}):
        result = dry_expand_embedded_workflows("Hello world")
    assert result == "Hello world"


def test_dry_expand_simple_prompt_part() -> None:
    """A simple #wf reference is replaced with its prompt_part content."""
    wf = _make_workflow("greet", "Hello from workflow!")
    with patch(_LOADER_PATH, return_value={"greet": wf}):
        result = dry_expand_embedded_workflows("Say #greet please")
    assert result == "Say Hello from workflow! please"


def test_dry_expand_with_args() -> None:
    """Workflow prompt_part with Jinja2 template and args renders correctly."""
    wf = _make_workflow(
        "greet",
        "Hello {{ name }}!",
        inputs=[InputArg(name="name", default=UNSET)],
    )
    with patch(_LOADER_PATH, return_value={"greet": wf}):
        result = dry_expand_embedded_workflows("Say #greet(World) please")
    assert result == "Say Hello World! please"


def test_dry_expand_colon_arg() -> None:
    """Colon syntax #wf:arg passes first positional arg."""
    wf = _make_workflow(
        "repo",
        "Repo: {{ name }}",
        inputs=[InputArg(name="name", default=UNSET)],
    )
    with patch(_LOADER_PATH, return_value={"repo": wf}):
        result = dry_expand_embedded_workflows("#repo:myrepo")
    assert result == "Repo: myrepo"


def test_dry_expand_colon_multi_arg() -> None:
    """Colon syntax #wf:a,b passes multiple positional args."""
    wf = _make_workflow(
        "deploy",
        "Deploy {{ app }} to {{ env }}",
        inputs=[
            InputArg(name="app", default=UNSET),
            InputArg(name="env", default=UNSET),
        ],
    )
    with patch(_LOADER_PATH, return_value={"deploy": wf}):
        result = dry_expand_embedded_workflows("#deploy:myapp,prod")
    assert result == "Deploy myapp to prod"


def test_dry_expand_plus_arg() -> None:
    """Plus syntax #wf+ passes 'true' as first positional arg."""
    wf = _make_workflow(
        "verbose",
        "Verbose: {{ enabled }}",
        inputs=[InputArg(name="enabled", default="false")],
    )
    with patch(_LOADER_PATH, return_value={"verbose": wf}):
        result = dry_expand_embedded_workflows("#verbose+")
    assert result == "Verbose: true"


def test_dry_expand_default_args() -> None:
    """Workflow inputs with defaults are applied when args are omitted."""
    wf = _make_workflow(
        "greet",
        "Hello {{ name }}!",
        inputs=[InputArg(name="name", default="World")],
    )
    with patch(_LOADER_PATH, return_value={"greet": wf}):
        result = dry_expand_embedded_workflows("#greet")
    assert result == "Hello World!"


def test_dry_expand_unknown_ref_left_asis() -> None:
    """References to unknown workflows are left untouched."""
    wf = _make_workflow("known", "expanded")
    with patch(_LOADER_PATH, return_value={"known": wf}):
        result = dry_expand_embedded_workflows("#unknown stays #known goes")
    assert result == "#unknown stays expanded goes"


def test_dry_expand_legacy_standalone_workflow_errors() -> None:
    """Legacy #standalone references are rejected in spec dry expansion."""
    wf = _make_standalone_workflow("deploy")
    with patch(_LOADER_PATH, return_value={"deploy": wf}):
        with pytest.raises(ValueError, match=r"Use `#!deploy`"):
            dry_expand_embedded_workflows("Run #deploy now")


def test_dry_expand_explicit_standalone_workflow_preserved() -> None:
    """Explicit #!standalone markers are preserved for spec storage."""
    wf = _make_standalone_workflow("deploy")
    with patch(_LOADER_PATH, return_value={"deploy": wf}):
        result = dry_expand_embedded_workflows("Run #!deploy now")
    assert result == "Run #!deploy now"


def test_dry_expand_standalone_workflow_in_fenced_block_protected() -> None:
    """Legacy standalone references inside fenced blocks are not inspected."""
    wf = _make_standalone_workflow("deploy")
    prompt = "Before\n```\n#deploy\n```\nAfter"
    with patch(_LOADER_PATH, return_value={"deploy": wf}):
        result = dry_expand_embedded_workflows(prompt)
    assert result == prompt


def test_dry_expand_bang_embeddable_workflow_errors() -> None:
    """Embeddable workflows must still use #name syntax."""
    wf = _make_workflow("commit", "Commit instructions")
    with patch(_LOADER_PATH, return_value={"commit": wf}):
        with pytest.raises(ValueError, match=r"only standalone workflows use `#!`"):
            dry_expand_embedded_workflows("Run #!commit now")


def test_dry_expand_multiple_workflows() -> None:
    """Multiple workflow references in one prompt are all expanded."""
    wf_a = _make_workflow("alpha", "A")
    wf_b = _make_workflow("beta", "B")
    with patch(_LOADER_PATH, return_value={"alpha": wf_a, "beta": wf_b}):
        result = dry_expand_embedded_workflows("#alpha and #beta")
    assert result == "A and B"


def test_dry_expand_fenced_code_block_protected() -> None:
    """Workflow references inside fenced code blocks are NOT expanded."""
    wf = _make_workflow("greet", "expanded")
    prompt = "Before\n```\n#greet\n```\nAfter #greet"
    with patch(_LOADER_PATH, return_value={"greet": wf}):
        result = dry_expand_embedded_workflows(prompt)
    assert "```\n#greet\n```" in result
    assert result.endswith("After expanded")


def test_dry_expand_no_pre_post_steps_executed() -> None:
    """Verify that no step execution methods are called (dry expansion)."""
    wf = _make_workflow("greet", "Hello!")
    with (
        patch(_LOADER_PATH, return_value={"greet": wf}),
        patch(
            "sase.xprompt.workflow_executor_utils.render_template",
            return_value="Hello!",
        ) as mock_render,
    ):
        result = dry_expand_embedded_workflows("#greet")
    assert result == "Hello!"
    # render_template should be called exactly once (for the prompt_part)
    mock_render.assert_called_once()


# ---------------------------------------------------------------------------
# expand_prompt_for_spec (integration of preprocessing + dry expansion)
# ---------------------------------------------------------------------------


def test_expand_prompt_for_spec_xprompt_expanded() -> None:
    """Simple xprompt references are expanded via preprocess_prompt_early."""
    with (
        patch(
            "sase.llm_provider.preprocessing.preprocess_prompt_early",
        ) as mock_preprocess,
        patch(_LOADER_PATH, return_value={}),
    ):
        from sase.llm_provider.preprocessing import PreprocessResult

        mock_preprocess.return_value = PreprocessResult(prompt="expanded content")
        result = expand_prompt_for_spec("#some_xprompt")
    assert result == "expanded content"
    mock_preprocess.assert_called_once_with("#some_xprompt")


def test_expand_prompt_for_spec_directives_removed() -> None:
    """Directives like %plan are stripped by preprocess_prompt_early."""
    with (
        patch(
            "sase.llm_provider.preprocessing.preprocess_prompt_early"
        ) as mock_preprocess,
        patch(_LOADER_PATH, return_value={}),
    ):
        from sase.llm_provider.preprocessing import PreprocessResult

        # Simulate that preprocessing already stripped directives
        mock_preprocess.return_value = PreprocessResult(prompt="clean prompt")
        result = expand_prompt_for_spec("%plan do something")
    assert result == "clean prompt"
    assert "%plan" not in result


def test_expand_prompt_for_spec_embedded_workflows_expanded() -> None:
    """Embedded workflow prompt_parts are expanded after preprocessing."""
    wf = _make_workflow("commit", "Commit instructions here")
    with (
        patch(
            "sase.llm_provider.preprocessing.preprocess_prompt_early"
        ) as mock_preprocess,
        patch(_LOADER_PATH, return_value={"commit": wf}),
    ):
        from sase.llm_provider.preprocessing import PreprocessResult

        mock_preprocess.return_value = PreprocessResult(prompt="Do #commit and finish")
        result = expand_prompt_for_spec("raw prompt")
    assert result == "Do Commit instructions here and finish"
