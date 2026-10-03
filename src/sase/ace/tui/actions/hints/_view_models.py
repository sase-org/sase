"""View-request value objects for sase's TUI app."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from sase.memory.legacy_glossary_read_report import GlossaryReadReportSpec
from sase.memory.memory_read_report import MemoryReadReportSpec

from ...artifact_reads import ArtifactReadRefSpec
from ...llm_calls.report import SlowToolCallReportSpec
from ...widgets.prompt_panel._agent_display_state import CommitViewSpec
from ._link_context_capture import CapturedLinkContext
from sase.pager.document import PagerSection
from sase.pager.link_context import LinkResolutionContext

type HintReportSpec = (
    SlowToolCallReportSpec | GlossaryReadReportSpec | MemoryReadReportSpec
)


@dataclass(frozen=True)
class ViewRequest:
    """Immutable destination intent captured from one submitted view action."""

    files: tuple[str, ...]
    open_in_editor: bool
    copy_to_clipboard: bool
    user_input: str
    patch_name: str
    commit_specs: tuple[CommitViewSpec, ...]
    captured_link_context: CapturedLinkContext
    bead_ids: tuple[str, ...] = ()
    tool_run_log_ids: tuple[str, ...] = ()
    tool_run_jump_ids: tuple[str, ...] = ()
    memory_version_pins: tuple[Any, ...] = ()


@dataclass(frozen=True)
class MaterializedReports:
    files: tuple[str, ...]
    failed_paths: tuple[str, ...]
    missing_paths: tuple[str, ...] = ()
    link_context: LinkResolutionContext = field(default_factory=LinkResolutionContext)
    bead_sections: tuple[PagerSection, ...] = ()
    bead_failures: tuple[str, ...] = ()


@dataclass(frozen=True)
class PreparedViewRequest:
    request: ViewRequest
    report_items: tuple[tuple[str, HintReportSpec], ...]
    artifact_read_ref_items: tuple[tuple[str, ArtifactReadRefSpec], ...] = ()
