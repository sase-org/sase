"""Macro system for typed prompt templates with argument validation.

This module provides a replacement for the legacy snippet system, adding:
- Markdown files with YAML front matter for defining input arguments
- Multiple discovery locations with priority ordering
- Type validation for input arguments
- Backward compatibility with existing #name(args) syntax
- YAML workflow support for multi-step agent workflows
"""

from ._parsing import (
    DEFAULT_VCS_WORKFLOW_PREFIX,
    MacroReference,
    MacroReferenceArgKind,
    MacroReferenceMarker,
    escape_for_macro,
    extract_project_from_vcs_tag,
    extract_vcs_workflow_tag,
    find_vcs_workflow_tag,
    find_vcs_workflow_tag_prepend_offset,
    find_vcs_workflow_tag_span,
    iter_macro_references,
    normalize_default_vcs_workflow,
    normalize_default_vcs_workflow_segment,
    normalize_launch_macro_at_refs,
    parse_workflow_reference,
    replace_ref_in_vcs_tag,
    replace_vcs_workflow_tags,
    strip_hitl_suffix,
    strip_vcs_workflow_tag,
    macro_reference_from_match,
)
from .alt_inspect import AltSpan
from .directives import PromptDirectives, extract_prompt_directives
from .jinja_assist import (
    JinjaAvailability,
    JinjaCatalog,
    JinjaCatalogFilter,
    JinjaCatalogGlobal,
    JinjaCatalogMember,
    JinjaCatalogStatement,
    JinjaCatalogTest,
    JinjaCatalogVariable,
    JinjaCompletion,
    JinjaCompletionItem,
    JinjaScope,
    JinjaScopeVariables,
    JinjaUnavailableVariable,
    jinja_catalog,
    jinja_completion,
    jinja_scope_variables,
)
from .jinja_inspect import (
    JinjaDiagnostics,
    JinjaSpan,
    diagnose,
    has_jinja,
    inspect_template,
    jinja_filter_names,
    matching_delimiter_spans,
    tokenize,
    undeclared_variables,
    unknown_variables,
)
from .loader import (
    get_all_project_local_prompts,
    get_all_prompts,
    get_all_workflows,
    get_all_macros,
    get_known_project_workspaces,
    get_macro_or_workflow,
    load_project_local_macros,
)
from .models import (
    InputArg,
    InputType,
    OutputSpec,
    Macro,
    MacroValidationError,
    create_anonymous_workflow,
    macro_to_workflow,
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
    LAUNCH_DEFERRED_MACRO_NAMES,
    is_jinja2_template,
    prompt_may_reference_macro,
    process_macro_references,
    process_macro_references_with_catalog,
    render_toplevel_jinja2,
    resolve_macro_aliases,
)
from .used_macros import collect_used_macros, write_used_macros
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
    "MacroReference",
    "MacroReferenceArgKind",
    "MacroReferenceMarker",
    "Macro",
    "MacroValidationError",
    "create_anonymous_workflow",
    "macro_to_workflow",
    # Alt inspection
    "AltSpan",
    # Jinja inspection
    "JinjaDiagnostics",
    "JinjaSpan",
    "diagnose",
    "has_jinja",
    "inspect_template",
    "jinja_filter_names",
    "matching_delimiter_spans",
    "tokenize",
    "undeclared_variables",
    "unknown_variables",
    # Jinja engine adapter (single source of truth with the macro LSP)
    "JinjaAvailability",
    "JinjaCatalog",
    "JinjaCatalogFilter",
    "JinjaCatalogGlobal",
    "JinjaCatalogMember",
    "JinjaCatalogStatement",
    "JinjaCatalogTest",
    "JinjaCatalogVariable",
    "JinjaCompletion",
    "JinjaCompletionItem",
    "JinjaScope",
    "JinjaScopeVariables",
    "JinjaUnavailableVariable",
    "jinja_catalog",
    "jinja_completion",
    "jinja_scope_variables",
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
    "get_all_macros",
    "get_known_project_workspaces",
    "get_macro_or_workflow",
    "load_project_local_macros",
    # Parsing
    "DEFAULT_VCS_WORKFLOW_PREFIX",
    "escape_for_macro",
    "extract_project_from_vcs_tag",
    "extract_vcs_workflow_tag",
    "find_vcs_workflow_tag",
    "find_vcs_workflow_tag_prepend_offset",
    "find_vcs_workflow_tag_span",
    "iter_macro_references",
    "normalize_default_vcs_workflow",
    "normalize_default_vcs_workflow_segment",
    "normalize_launch_macro_at_refs",
    "parse_workflow_reference",
    "replace_ref_in_vcs_tag",
    "replace_vcs_workflow_tags",
    "strip_hitl_suffix",
    "strip_vcs_workflow_tag",
    "macro_reference_from_match",
    # Directives
    "PromptDirectives",
    "extract_prompt_directives",
    # Trace
    "ExpansionRecord",
    "ExpansionTrace",
    "format_trace",
    "print_trace",
    # Processor
    "LAUNCH_DEFERRED_MACRO_NAMES",
    "WorkflowResult",
    "execute_workflow",
    "expand_workflow_for_embedding",
    "is_jinja2_template",
    "is_workflow_reference",
    "prompt_may_reference_macro",
    "process_macro_references",
    "process_macro_references_with_catalog",
    "render_toplevel_jinja2",
    "resolve_macro_aliases",
    "collect_used_macros",
    "write_used_macros",
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
