"""XPrompt system for typed prompt templates with argument validation.

This module provides a replacement for the legacy snippet system, adding:
- Markdown files with YAML front matter for defining input arguments
- Multiple discovery locations with priority ordering
- Type validation for input arguments
- Backward compatibility with existing #name(args) syntax
- YAML workflow support for multi-step agent workflows
"""

from ._parsing import (
    DEFAULT_VCS_WORKFLOW_PREFIX,
    XPromptReference,
    XPromptReferenceArgKind,
    XPromptReferenceMarker,
    escape_for_xprompt,
    extract_project_from_vcs_tag,
    extract_vcs_workflow_tag,
    find_vcs_workflow_tag,
    find_vcs_workflow_tag_prepend_offset,
    find_vcs_workflow_tag_span,
    iter_xprompt_references,
    normalize_default_vcs_workflow,
    normalize_default_vcs_workflow_segment,
    normalize_launch_xprompt_at_refs,
    parse_workflow_reference,
    replace_ref_in_vcs_tag,
    replace_vcs_workflow_tags,
    strip_hitl_suffix,
    strip_vcs_workflow_tag,
    xprompt_reference_from_match,
)
from .alt_inspect import AltSpan
from .directives import PromptDirectives, extract_prompt_directives
from .jinja_inspect import (
    JinjaCompletionContext,
    JinjaDiagnostics,
    JinjaSpan,
    builtin_runtime_member_names,
    builtin_runtime_names,
    completion_context,
    diagnose,
    has_jinja,
    inspect_template,
    jinja_filter_names,
    known_toplevel_context,
    matching_delimiter_spans,
    tokenize,
    unknown_variables,
)
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
    LAUNCH_DEFERRED_XPROMPT_NAMES,
    is_jinja2_template,
    prompt_may_reference_xprompt,
    process_xprompt_references,
    process_xprompt_references_with_catalog,
    render_toplevel_jinja2,
    resolve_xprompt_aliases,
)
from .used_xprompts import collect_used_xprompts, write_used_xprompts
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
    # Alt inspection
    "AltSpan",
    # Jinja inspection
    "JinjaCompletionContext",
    "JinjaDiagnostics",
    "JinjaSpan",
    "builtin_runtime_member_names",
    "builtin_runtime_names",
    "completion_context",
    "diagnose",
    "has_jinja",
    "inspect_template",
    "jinja_filter_names",
    "known_toplevel_context",
    "matching_delimiter_spans",
    "tokenize",
    "unknown_variables",
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
    "DEFAULT_VCS_WORKFLOW_PREFIX",
    "escape_for_xprompt",
    "extract_project_from_vcs_tag",
    "extract_vcs_workflow_tag",
    "find_vcs_workflow_tag",
    "find_vcs_workflow_tag_prepend_offset",
    "find_vcs_workflow_tag_span",
    "iter_xprompt_references",
    "normalize_default_vcs_workflow",
    "normalize_default_vcs_workflow_segment",
    "normalize_launch_xprompt_at_refs",
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
    "LAUNCH_DEFERRED_XPROMPT_NAMES",
    "WorkflowResult",
    "execute_workflow",
    "expand_workflow_for_embedding",
    "is_jinja2_template",
    "is_workflow_reference",
    "prompt_may_reference_xprompt",
    "process_xprompt_references",
    "process_xprompt_references_with_catalog",
    "render_toplevel_jinja2",
    "resolve_xprompt_aliases",
    "collect_used_xprompts",
    "write_used_xprompts",
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
