"""Name planning and reference rewrites for multi-prompt launches.

This compatibility module preserves the original import path while the
implementation lives in focused sibling modules.
"""

from sase.agent.multi_prompt_reference_allocator import PlannedNameAllocator
from sase.agent.multi_prompt_reference_directives import (
    StaticFamilyDirective,
    extract_static_family_directive,
    extract_static_name_directive,
    has_bare_wait_directive,
    rewrite_bare_wait_directives,
)
from sase.agent.multi_prompt_reference_naming import (
    _GENERATED_AGENT_NAME_ENV,
    _PLANNED_AGENT_NAME_ENV,
    wait_for_agent_naming,
)
from sase.agent.multi_prompt_reference_resume import (
    has_bare_resume_reference,
    rewrite_bare_resume_references,
)

__all__ = [
    "PlannedNameAllocator",
    "StaticFamilyDirective",
    "_GENERATED_AGENT_NAME_ENV",
    "_PLANNED_AGENT_NAME_ENV",
    "extract_static_family_directive",
    "extract_static_name_directive",
    "has_bare_resume_reference",
    "has_bare_wait_directive",
    "rewrite_bare_resume_references",
    "rewrite_bare_wait_directives",
    "wait_for_agent_naming",
]
