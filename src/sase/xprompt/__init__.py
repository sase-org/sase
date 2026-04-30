"""XPrompt system for typed prompt templates with argument validation.

This module provides a replacement for the legacy snippet system, adding:
- Markdown files with YAML front matter for defining input arguments
- Multiple discovery locations with priority ordering
- Type validation for input arguments
- Backward compatibility with existing #name(args) syntax
- YAML workflow support for multi-step agent workflows
"""

from ._parsing import (
    XPromptReference,
    XPromptReferenceArgKind,
    XPromptReferenceMarker,
    escape_for_xprompt,
    extract_project_from_vcs_tag,
    extract_vcs_workflow_tag,
    iter_xprompt_references,
    normalize_default_vcs_workflow,
    normalize_default_vcs_workflow_segment,
    parse_workflow_reference,
    replace_ref_in_vcs_tag,
    replace_vcs_workflow_tags,
    strip_hitl_suffix,
    strip_vcs_workflow_tag,
    xprompt_reference_from_match,
)
from .directives import PromptDirectives, extract_prompt_directives
from .loader import (
    get_all_project_local_prompts,
    get_all_prompts,
    get_all_workflows,
    get_all_xprompts,
    get_known_project_workspaces,
    get_xprompt_or_workflow,
    load_project_local_xprompts,
)
from .models import (
    InputArg,
    InputType,
    OutputSpec,
    XPrompt,
    XPromptValidationError,
    create_anonymous_workflow,
    xprompt_to_workflow,
)
from .output_validation import (
    OutputValidationError,
    extract_semantic_type_hints,
    extract_structured_content,
    generate_format_instructions,
    validate_against_schema,
    validate_response,
)
from ._trace import ExpansionRecord, ExpansionTrace, format_trace, print_trace
from .processor import (
    is_jinja2_template,
    prompt_may_reference_xprompt,
    process_xprompt_references,
    render_toplevel_jinja2,
    resolve_xprompt_aliases,
)
from .workflow_runner import (
    WorkflowResult,
    execute_workflow,
    expand_workflow_for_embedding,
    is_workflow_reference,
)
from .workflow_executor import HITLHandler, HITLResult, WorkflowExecutor
from .workflow_hitl import CLIHITLHandler
from .workflow_models import (
    StepState,
    StepStatus,
    Workflow,
    WorkflowError,
    WorkflowExecutionError,
    WorkflowKind,
    WorkflowState,
    WorkflowStep,
    WorkflowValidationError,
)
from .workflow_output import LoopInfo, WorkflowOutputHandler

__all__ = [
    # Models
    "InputArg",
    "InputType",
    "OutputSpec",
    "XPromptReference",
    "XPromptReferenceArgKind",
    "XPromptReferenceMarker",
    "XPrompt",
    "XPromptValidationError",
    "create_anonymous_workflow",
    "xprompt_to_workflow",
    # Output validation
    "OutputValidationError",
    "extract_semantic_type_hints",
    "extract_structured_content",
    "generate_format_instructions",
    "validate_against_schema",
    "validate_response",
    # Loader
    "get_all_project_local_prompts",
    "get_all_prompts",
    "get_all_workflows",
    "get_all_xprompts",
    "get_known_project_workspaces",
    "get_xprompt_or_workflow",
    "load_project_local_xprompts",
    # Parsing
    "escape_for_xprompt",
    "extract_project_from_vcs_tag",
    "extract_vcs_workflow_tag",
    "iter_xprompt_references",
    "normalize_default_vcs_workflow",
    "normalize_default_vcs_workflow_segment",
    "parse_workflow_reference",
    "replace_ref_in_vcs_tag",
    "replace_vcs_workflow_tags",
    "strip_hitl_suffix",
    "strip_vcs_workflow_tag",
    "xprompt_reference_from_match",
    # Directives
    "PromptDirectives",
    "extract_prompt_directives",
    # Trace
    "ExpansionRecord",
    "ExpansionTrace",
    "format_trace",
    "print_trace",
    # Processor
    "WorkflowResult",
    "execute_workflow",
    "expand_workflow_for_embedding",
    "is_jinja2_template",
    "is_workflow_reference",
    "prompt_may_reference_xprompt",
    "process_xprompt_references",
    "render_toplevel_jinja2",
    "resolve_xprompt_aliases",
    # Workflow models
    "StepState",
    "StepStatus",
    "Workflow",
    "WorkflowError",
    "WorkflowExecutionError",
    "WorkflowExecutor",
    "WorkflowKind",
    "WorkflowState",
    "WorkflowStep",
    "WorkflowValidationError",
    # Workflow execution
    "CLIHITLHandler",
    "HITLHandler",
    "HITLResult",
    # Workflow output
    "LoopInfo",
    "WorkflowOutputHandler",
]
