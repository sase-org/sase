"""Off-thread enrichment loading and detail rendering for the Agent pane.

Everything :class:`~.agents_data.AgentsSnapshot` already carries (identity,
kind, lifecycle, timing, model/provider, family/clan/tribe, retry pointers,
provenance) is local truth and renders with zero I/O. This module owns the
handful of fields that genuinely need a filesystem read for the selected
row only: the raw prompt, the chat path, and (best-effort) the published
agents-sidecar page — mirroring ``files_detail.py``'s shape for the Files
pane's own lazy, per-row enrichment.
"""

from __future__ import annotations

from dataclasses import dataclass
import os

from rich.text import Text

from sase.agent.artifact_files_cache import get_global_cache
from sase.agents.catalog import AgentCatalogRow
from sase.agents.status_style import agent_status_text
from sase.core.agent_artifact_paths import resolve_agent_artifact_path
from sase.core.time import format_local

from .types import ARTIFACTS_ACCENTS

_PROMPT_PREVIEW_CHARS = 4000

AgentDetailCacheKey = tuple[str, str | None, str | None]


@dataclass(frozen=True, slots=True)
class AgentDetailData:
    """Filesystem facts loaded without blocking Textual's message pump."""

    name: str
    artifacts_dir_live: bool
    resolved_artifacts_dir: str | None
    prompt_preview: str | None
    prompt_truncated: bool
    chat_path: str | None
    page_url: str | None

    @property
    def cache_key(self) -> AgentDetailCacheKey:
        return (self.name, self.resolved_artifacts_dir, self.chat_path)


def load_agent_detail(row: AgentCatalogRow) -> AgentDetailData:
    """Resolve the artifacts dir and read its prompt/chat metadata off-thread."""

    resolved_dir: str | None = None
    live = False
    if row.artifacts_dir:
        try:
            resolved = resolve_agent_artifact_path(row.artifacts_dir)
        except Exception:  # noqa: BLE001 - a bad path degrades to a thin row
            resolved = None
        if resolved is not None and resolved.is_dir():
            resolved_dir = str(resolved)
            live = True

    prompt_preview: str | None = None
    prompt_truncated = False
    chat_path: str | None = None
    if resolved_dir is not None:
        cache = get_global_cache()
        raw_prompt = cache.read_text(os.path.join(resolved_dir, "raw_xprompt.md"))
        if raw_prompt is not None:
            prompt_truncated = len(raw_prompt) > _PROMPT_PREVIEW_CHARS
            prompt_preview = raw_prompt[:_PROMPT_PREVIEW_CHARS]
        meta = cache.read_json(os.path.join(resolved_dir, "agent_meta.json"))
        if isinstance(meta, dict):
            candidate = meta.get("chat_path")
            if isinstance(candidate, str) and candidate:
                chat_path = candidate

    return AgentDetailData(
        name=row.name,
        artifacts_dir_live=live,
        resolved_artifacts_dir=resolved_dir,
        prompt_preview=prompt_preview,
        prompt_truncated=prompt_truncated,
        chat_path=chat_path,
        page_url=_agent_page_url(row),
    )


def _agent_page_url(row: AgentCatalogRow) -> str | None:
    """Best-effort hosted sidecar page URL; ``None`` on any resolution gap."""
    if not row.project or row.dismissed or "family" in row.kind or "clan" in row.kind:
        return None
    try:
        from sase.core.paths import sase_projects_dir
        from sase.sdd.hosted_links import hosted_link_resolver
        from sase.sdd.store import resolve_sdd_store

        primary_root = sase_projects_dir() / row.project
        store = resolve_sdd_store(primary_root, 1)
        resolver = hosted_link_resolver(
            store,
            project=row.project,
            primary_root=primary_root,
        )
        return resolver.agent_url(row.name)
    except Exception:  # noqa: BLE001 - the page section degrades to "none"
        return None


def build_agent_detail(
    row: AgentCatalogRow | None,
    detail: AgentDetailData | None,
    *,
    loading: bool = False,
) -> Text:
    """Render identity, lifecycle, provenance, and lazy enrichment sections."""

    if row is None:
        return Text("Select an agent to see its details.", style="dim")

    text = Text()
    _heading(text, "REFERENCE")
    text.append(f"agent:{row.canonical_global_name or row.name}", style="bold")
    text.append("\n")

    _heading(text, "IDENTITY")
    _field(text, "Name", row.name)
    _field(text, "Kind", "/".join(row.kind) if row.kind else "-")
    _field(text, "Project", row.project)
    _field(text, "State", row.state)
    if row.status:
        text.append("Status: ", style="bold #87AFFF")
        text.append_text(agent_status_text(row.status.upper()))
        text.append("\n")
    else:
        _field(text, "Status", None)

    _heading(text, "LIFECYCLE")
    _field(text, "Dismissed", _yes_no(row.dismissed))
    _field(text, "Revivable", _yes_no(row.revivable))
    _field(text, "Attention", _yes_no(row.attention))
    _field(text, "Hidden", _yes_no(row.hidden))

    _heading(text, "TIMING")
    _field(text, "Started", _minute_precision(row.started_at))
    _field(text, "Finished", _minute_precision(row.finished_at))

    _heading(text, "EXECUTION")
    _field(text, "Model", row.model)
    _field(text, "Provider", row.llm_provider)
    _field(text, "Patch", row.patch)

    _heading(text, "FAMILY & LINEAGE")
    _field(text, "Family", row.family)
    _field(text, "Role", row.role)
    _field(text, "Clan", row.clan)
    _field(text, "Tribe", row.tribe)
    _field(text, "Workflow", row.workflow)
    if row.retry:
        _field(text, "Retry attempt", row.retry_attempt)
    _field(text, "Collision history", _yes_no(row.has_collision_history))

    _heading(text, "PROVENANCE")
    _field(text, "Artifact index", _yes_no(row.from_artifact_index))
    _field(text, "Dismissed archive", _yes_no(row.from_dismissed_archive))

    _heading(text, "PROMPT")
    if detail is None:
        text.append(
            "Loading prompt…\n" if loading else "Prompt not loaded yet.\n",
            style="dim",
        )
    elif detail.prompt_preview is None:
        text.append("No prompt available for this agent.\n", style="dim")
    else:
        text.append(detail.prompt_preview or "_Empty prompt._", style="dim")
        text.append("\n")
        if detail.prompt_truncated:
            text.append("… truncated\n", style="dim italic")

    _heading(text, "CHAT")
    if detail is None:
        text.append("Loading…\n" if loading else "Not loaded yet.\n", style="dim")
    elif detail.chat_path is None:
        text.append("No chat file recorded for this agent.\n", style="dim")
    else:
        text.append(detail.chat_path, style="dim")
        text.append("\n")

    _heading(text, "PUBLISHED PAGE")
    if detail is None:
        text.append("Loading…\n" if loading else "Not loaded yet.\n", style="dim")
    elif detail.page_url is None:
        text.append("No published sidecar page.\n", style="dim")
    else:
        text.append(detail.page_url, style="dim")
        text.append("\n")

    return text


def _yes_no(value: bool) -> str:
    return "yes" if value else "no"


def _minute_precision(value: str | float | None) -> str | None:
    return None if value is None else format_local(value, "%Y-%m-%d %H:%M", default="-")


def _heading(text: Text, label: str) -> None:
    if text:
        text.append("\n")
    text.append(
        f"{label}\n",
        style=f"bold underline {ARTIFACTS_ACCENTS['agents']}",
    )


def _field(text: Text, label: str, value: object | None) -> None:
    text.append(f"{label}: ", style="bold #87AFFF")
    text.append(f"{value if value not in (None, '') else '-'}\n")


__all__ = [
    "AgentDetailCacheKey",
    "AgentDetailData",
    "build_agent_detail",
    "load_agent_detail",
]
