"""Macro system for typed prompt templates with argument validation.

This module provides a replacement for the legacy snippet system, adding:
- Markdown files with YAML front matter for defining input arguments
- Multiple discovery locations with priority ordering
- Type validation for input arguments
- Backward compatibility with existing #name(args) syntax
- YAML workflow support for multi-step agent workflows

Package-level attributes are lazy re-exports (PEP 562): importing
``sase.macro.models`` (or any other submodule) does not execute the
jinja/loader/processor/workflow closures until those attributes are
actually accessed.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from sase._lazy_exports import LazyExportMap, lazy_dir, lazy_getattr

_EXPORTS: LazyExportMap = {
    "DEFAULT_VCS_WORKFLOW_PREFIX": (
        "sase.macro._parsing",
        "DEFAULT_VCS_WORKFLOW_PREFIX",
    ),
    "MacroReference": ("sase.macro._parsing", "MacroReference"),
    "MacroReferenceArgKind": ("sase.macro._parsing", "MacroReferenceArgKind"),
    "MacroReferenceMarker": ("sase.macro._parsing", "MacroReferenceMarker"),
    "escape_for_macro": ("sase.macro._parsing", "escape_for_macro"),
    "extract_project_from_vcs_tag": (
        "sase.macro._parsing",
        "extract_project_from_vcs_tag",
    ),
    "extract_vcs_workflow_tag": ("sase.macro._parsing", "extract_vcs_workflow_tag"),
    "find_vcs_workflow_tag": ("sase.macro._parsing", "find_vcs_workflow_tag"),
    "find_vcs_workflow_tag_prepend_offset": (
        "sase.macro._parsing",
        "find_vcs_workflow_tag_prepend_offset",
    ),
    "find_vcs_workflow_tag_span": (
        "sase.macro._parsing",
        "find_vcs_workflow_tag_span",
    ),
    "iter_macro_references": ("sase.macro._parsing", "iter_macro_references"),
    "normalize_default_vcs_workflow": (
        "sase.macro._parsing",
        "normalize_default_vcs_workflow",
    ),
    "normalize_default_vcs_workflow_segment": (
        "sase.macro._parsing",
        "normalize_default_vcs_workflow_segment",
    ),
    "normalize_launch_macro_at_refs": (
        "sase.macro._parsing",
        "normalize_launch_macro_at_refs",
    ),
    "parse_workflow_reference": ("sase.macro._parsing", "parse_workflow_reference"),
    "replace_ref_in_vcs_tag": ("sase.macro._parsing", "replace_ref_in_vcs_tag"),
    "replace_vcs_workflow_tags": (
        "sase.macro._parsing",
        "replace_vcs_workflow_tags",
    ),
    "strip_hitl_suffix": ("sase.macro._parsing", "strip_hitl_suffix"),
    "strip_vcs_workflow_tag": ("sase.macro._parsing", "strip_vcs_workflow_tag"),
    "macro_reference_from_match": (
        "sase.macro._parsing",
        "macro_reference_from_match",
    ),
    "AltSpan": ("sase.macro.alt_inspect", "AltSpan"),
    "PromptDirectives": ("sase.macro.directives", "PromptDirectives"),
    "extract_prompt_directives": (
        "sase.macro.directives",
        "extract_prompt_directives",
    ),
    "JinjaAvailability": ("sase.macro.jinja_assist", "JinjaAvailability"),
    "JinjaCatalog": ("sase.macro.jinja_assist", "JinjaCatalog"),
    "JinjaCatalogFilter": ("sase.macro.jinja_assist", "JinjaCatalogFilter"),
    "JinjaCatalogGlobal": ("sase.macro.jinja_assist", "JinjaCatalogGlobal"),
    "JinjaCatalogMember": ("sase.macro.jinja_assist", "JinjaCatalogMember"),
    "JinjaCatalogStatement": ("sase.macro.jinja_assist", "JinjaCatalogStatement"),
    "JinjaCatalogTest": ("sase.macro.jinja_assist", "JinjaCatalogTest"),
    "JinjaCatalogVariable": ("sase.macro.jinja_assist", "JinjaCatalogVariable"),
    "JinjaCompletion": ("sase.macro.jinja_assist", "JinjaCompletion"),
    "JinjaCompletionItem": ("sase.macro.jinja_assist", "JinjaCompletionItem"),
    "JinjaScope": ("sase.macro.jinja_assist", "JinjaScope"),
    "JinjaScopeVariables": ("sase.macro.jinja_assist", "JinjaScopeVariables"),
    "JinjaUnavailableVariable": (
        "sase.macro.jinja_assist",
        "JinjaUnavailableVariable",
    ),
    "jinja_catalog": ("sase.macro.jinja_assist", "jinja_catalog"),
    "jinja_completion": ("sase.macro.jinja_assist", "jinja_completion"),
    "jinja_scope_variables": ("sase.macro.jinja_assist", "jinja_scope_variables"),
    "JinjaDiagnostics": ("sase.macro.jinja_inspect", "JinjaDiagnostics"),
    "JinjaSpan": ("sase.macro.jinja_inspect", "JinjaSpan"),
    "diagnose": ("sase.macro.jinja_inspect", "diagnose"),
    "has_jinja": ("sase.macro.jinja_inspect", "has_jinja"),
    "inspect_template": ("sase.macro.jinja_inspect", "inspect_template"),
    "jinja_filter_names": ("sase.macro.jinja_inspect", "jinja_filter_names"),
    "matching_delimiter_spans": (
        "sase.macro.jinja_inspect",
        "matching_delimiter_spans",
    ),
    "tokenize": ("sase.macro.jinja_inspect", "tokenize"),
    "undeclared_variables": ("sase.macro.jinja_inspect", "undeclared_variables"),
    "unknown_variables": ("sase.macro.jinja_inspect", "unknown_variables"),
    "get_all_project_local_prompts": (
        "sase.macro.loader",
        "get_all_project_local_prompts",
    ),
    "get_all_prompts": ("sase.macro.loader", "get_all_prompts"),
    "get_all_workflows": ("sase.macro.loader", "get_all_workflows"),
    "get_all_macros": ("sase.macro.loader", "get_all_macros"),
    "get_known_project_workspaces": (
        "sase.macro.loader",
        "get_known_project_workspaces",
    ),
    "get_macro_or_workflow": ("sase.macro.loader", "get_macro_or_workflow"),
    "load_project_local_macros": ("sase.macro.loader", "load_project_local_macros"),
    "InputArg": ("sase.macro.models", "InputArg"),
    "InputType": ("sase.macro.models", "InputType"),
    "OutputSpec": ("sase.macro.models", "OutputSpec"),
    "Macro": ("sase.macro.models", "Macro"),
    "MacroValidationError": ("sase.macro.models", "MacroValidationError"),
    "create_anonymous_workflow": (
        "sase.macro.models",
        "create_anonymous_workflow",
    ),
    "macro_to_workflow": ("sase.macro.models", "macro_to_workflow"),
    "OutputValidationError": (
        "sase.macro.output_validation",
        "OutputValidationError",
    ),
    "extract_semantic_type_hints": (
        "sase.macro.output_validation",
        "extract_semantic_type_hints",
    ),
    "extract_structured_content": (
        "sase.macro.output_validation",
        "extract_structured_content",
    ),
    "generate_format_instructions": (
        "sase.macro.output_validation",
        "generate_format_instructions",
    ),
    "validate_against_schema": (
        "sase.macro.output_validation",
        "validate_against_schema",
    ),
    "validate_response": ("sase.macro.output_validation", "validate_response"),
    "ExpansionRecord": ("sase.macro._trace", "ExpansionRecord"),
    "ExpansionTrace": ("sase.macro._trace", "ExpansionTrace"),
    "format_trace": ("sase.macro._trace", "format_trace"),
    "print_trace": ("sase.macro._trace", "print_trace"),
    "LAUNCH_DEFERRED_MACRO_NAMES": (
        "sase.macro.processor",
        "LAUNCH_DEFERRED_MACRO_NAMES",
    ),
    "is_jinja2_template": ("sase.macro.processor", "is_jinja2_template"),
    "prompt_may_reference_macro": (
        "sase.macro.processor",
        "prompt_may_reference_macro",
    ),
    "process_macro_references": (
        "sase.macro.processor",
        "process_macro_references",
    ),
    "process_macro_references_with_catalog": (
        "sase.macro.processor",
        "process_macro_references_with_catalog",
    ),
    "render_toplevel_jinja2": ("sase.macro.processor", "render_toplevel_jinja2"),
    "resolve_macro_aliases": ("sase.macro.processor", "resolve_macro_aliases"),
    "collect_used_macros": ("sase.macro.used_macros", "collect_used_macros"),
    "write_used_macros": ("sase.macro.used_macros", "write_used_macros"),
    "WorkflowResult": ("sase.macro.workflow_runner", "WorkflowResult"),
    "execute_workflow": ("sase.macro.workflow_runner", "execute_workflow"),
    "expand_workflow_for_embedding": (
        "sase.macro.workflow_runner",
        "expand_workflow_for_embedding",
    ),
    "is_workflow_reference": (
        "sase.macro.workflow_runner",
        "is_workflow_reference",
    ),
    "HITLHandler": ("sase.macro.workflow_executor_types", "HITLHandler"),
    "HITLResult": ("sase.macro.workflow_executor_types", "HITLResult"),
    "WorkflowExecutor": ("sase.macro.workflow_executor", "WorkflowExecutor"),
    "WorkflowSuspended": ("sase.macro.workflow_executor_types", "WorkflowSuspended"),
    "CLIHITLHandler": ("sase.macro.workflow_hitl", "CLIHITLHandler"),
    "StepState": ("sase.macro.workflow_models", "StepState"),
    "StepStatus": ("sase.macro.workflow_models", "StepStatus"),
    "Workflow": ("sase.macro.workflow_models", "Workflow"),
    "WorkflowError": ("sase.macro.workflow_models", "WorkflowError"),
    "WorkflowExecutionError": (
        "sase.macro.workflow_models",
        "WorkflowExecutionError",
    ),
    "WorkflowKind": ("sase.macro.workflow_models", "WorkflowKind"),
    "WorkflowState": ("sase.macro.workflow_models", "WorkflowState"),
    "WorkflowStep": ("sase.macro.workflow_models", "WorkflowStep"),
    "WorkflowValidationError": (
        "sase.macro.workflow_models",
        "WorkflowValidationError",
    ),
    "LoopInfo": ("sase.macro.workflow_output", "LoopInfo"),
    "WorkflowOutputHandler": (
        "sase.macro.workflow_output",
        "WorkflowOutputHandler",
    ),
}

__all__ = [
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
    "AltSpan",
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
    "OutputValidationError",
    "extract_semantic_type_hints",
    "extract_structured_content",
    "generate_format_instructions",
    "validate_against_schema",
    "validate_response",
    "get_all_project_local_prompts",
    "get_all_prompts",
    "get_all_workflows",
    "get_all_macros",
    "get_known_project_workspaces",
    "get_macro_or_workflow",
    "load_project_local_macros",
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
    "PromptDirectives",
    "extract_prompt_directives",
    "ExpansionRecord",
    "ExpansionTrace",
    "format_trace",
    "print_trace",
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
    "StepState",
    "StepStatus",
    "Workflow",
    "WorkflowError",
    "WorkflowExecutionError",
    "WorkflowExecutor",
    "WorkflowSuspended",
    "WorkflowKind",
    "WorkflowState",
    "WorkflowStep",
    "WorkflowValidationError",
    "CLIHITLHandler",
    "HITLHandler",
    "HITLResult",
    "LoopInfo",
    "WorkflowOutputHandler",
]

if TYPE_CHECKING:
    from sase.macro._parsing import (
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
        macro_reference_from_match,
        normalize_default_vcs_workflow,
        normalize_default_vcs_workflow_segment,
        normalize_launch_macro_at_refs,
        parse_workflow_reference,
        replace_ref_in_vcs_tag,
        replace_vcs_workflow_tags,
        strip_hitl_suffix,
        strip_vcs_workflow_tag,
    )
    from sase.macro._trace import (
        ExpansionRecord,
        ExpansionTrace,
        format_trace,
        print_trace,
    )
    from sase.macro.alt_inspect import AltSpan
    from sase.macro.directives import PromptDirectives, extract_prompt_directives
    from sase.macro.jinja_assist import (
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
    from sase.macro.jinja_inspect import (
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
    from sase.macro.loader import (
        get_all_macros,
        get_all_project_local_prompts,
        get_all_prompts,
        get_all_workflows,
        get_known_project_workspaces,
        get_macro_or_workflow,
        load_project_local_macros,
    )
    from sase.macro.models import (
        InputArg,
        InputType,
        Macro,
        MacroValidationError,
        OutputSpec,
        create_anonymous_workflow,
        macro_to_workflow,
    )
    from sase.macro.output_validation import (
        OutputValidationError,
        extract_semantic_type_hints,
        extract_structured_content,
        generate_format_instructions,
        validate_against_schema,
        validate_response,
    )
    from sase.macro.processor import (
        LAUNCH_DEFERRED_MACRO_NAMES,
        is_jinja2_template,
        process_macro_references,
        process_macro_references_with_catalog,
        prompt_may_reference_macro,
        render_toplevel_jinja2,
        resolve_macro_aliases,
    )
    from sase.macro.used_macros import collect_used_macros, write_used_macros
    from sase.macro.workflow_executor import WorkflowExecutor
    from sase.macro.workflow_executor_types import (
        HITLHandler,
        HITLResult,
        WorkflowSuspended,
    )
    from sase.macro.workflow_hitl import CLIHITLHandler
    from sase.macro.workflow_models import (
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
    from sase.macro.workflow_output import LoopInfo, WorkflowOutputHandler
    from sase.macro.workflow_runner import (
        WorkflowResult,
        execute_workflow,
        expand_workflow_for_embedding,
        is_workflow_reference,
    )


def __getattr__(name: str) -> Any:
    return lazy_getattr(__name__, globals(), _EXPORTS, name)


def __dir__() -> list[str]:
    return lazy_dir(globals(), _EXPORTS)


# Symvision cannot see Python's package-level lazy hook lookup.
_PACKAGE_GETATTR = __getattr__
_PACKAGE_DIR = __dir__
_LAZY_EXPORTS = _EXPORTS
_PEP562_HOOKS = (__getattr__, __dir__)
