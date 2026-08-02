"""Off-thread detail loading and Rich rendering for Artifacts Chats."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
import json
from pathlib import Path

from rich.text import Text

from sase.artifact_refs import ArtifactRefContext, reference_for_entry_target
from sase.core.agent_identity_facade import present_agent_name
from sase.core.paths import sase_subdir
from sase.history.chat_catalog_provenance import ChatCatalogEntry
from sase.history.chat_prompt_sections import (
    RENDERED_SECTION_END,
    RENDERED_SECTION_START,
    XPROMPT_SECTION_END,
    XPROMPT_SECTION_START,
    StoredPromptRenderings,
    extract_prompt_renderings,
)

from .chats_rendering import CHAT_PROVENANCE_COLORS, CHAT_PROVENANCE_GLYPHS
from .types import ARTIFACTS_ACCENTS

_TRANSCRIPT_PREVIEW_LINES = 200
_PROMPT_RENDERING_PREVIEW_LINES = 120


@dataclass(frozen=True, slots=True)
class ChatDetailData:
    """Bounded transcript and agent facts loaded away from the event loop."""

    absolute_path: str
    transcript_preview: str
    transcript_truncated: bool
    xprompt_prompt: str | None = None
    rendered_prompt: str | None = None
    reference: str | None = None
    model: str | None = None
    provider: str | None = None
    agent_status: str | None = None
    dismissed: bool | None = None


def load_chat_detail(entry: ChatCatalogEntry) -> ChatDetailData:
    """Read bounded transcript and artifact facts for one selected row."""

    preview, truncated, renderings = _read_transcript_preview(Path(entry.absolute_path))
    if not preview:
        preview = _snippet_fallback(entry)
    meta: dict[str, object] = {}
    done: dict[str, object] = {}
    if entry.agent_artifact_dir:
        artifact_dir = Path(entry.agent_artifact_dir)
        meta = _read_mapping(artifact_dir / "agent_meta.json")
        done = _read_mapping(artifact_dir / "done.json")
    model = _first_text(meta, done, keys=("model", "model_name"))
    provider = _first_text(
        meta,
        done,
        keys=("llm_provider", "provider", "runtime"),
    )
    status = _first_text(meta, done, keys=("status", "outcome"))
    if status is None and done:
        status = "DONE"
    elif status is None and meta:
        status = "RUNNING"
    dismissed = _is_dismissed(entry) if entry.agent_artifact_dir else None
    return ChatDetailData(
        absolute_path=entry.absolute_path,
        transcript_preview=preview,
        transcript_truncated=truncated,
        xprompt_prompt=renderings.xprompt_prompt,
        rendered_prompt=renderings.rendered_prompt,
        reference=chat_reference(entry.absolute_path),
        model=model,
        provider=provider,
        agent_status=status,
        dismissed=dismissed,
    )


def read_full_chat(entry: ChatCatalogEntry) -> str:
    """Read the selected transcript for the user-requested preview modal."""

    try:
        return Path(entry.absolute_path).read_text(
            encoding="utf-8",
            errors="replace",
        )
    except OSError:
        return _snippet_fallback(entry)


def build_chat_detail(
    entry: ChatCatalogEntry | None,
    detail: ChatDetailData | None,
    *,
    diagnostics: tuple[str, ...] = (),
    loading: bool = False,
) -> Text:
    """Build detail sections from cached catalog/detail data."""

    if entry is None:
        return Text("Select a chat transcript to inspect it.", style="dim")

    text = Text()
    _heading(text, "PROVENANCE")
    _provenance_section(text, entry, diagnostics)
    _heading(text, "CHAT")
    _field(text, "Workflow", entry.workflow)
    agent = entry.agent_local_name or entry.agent
    _field(text, "Agent", present_agent_name(agent) if agent else None)
    if detail is not None:
        model_provider = " / ".join(
            value for value in (detail.provider, detail.model) if value
        )
        _field(text, "Model", model_provider or None)
    _field(text, "Timestamp", entry.mtime)
    _field(text, "Size", _format_size(entry.size_bytes))
    _field(text, "Project", entry.project_key)
    if detail is not None:
        _field(text, "Reference", detail.reference)
    _field(text, "Path", entry.absolute_path)

    _heading(text, "AGENT")
    if entry.agent_artifact_dir is None:
        noun = "agent" if entry.provenance == "unknown" else "local agent"
        text.append(
            f"No {noun} artifact — this transcript cannot be revived.\n",
            style="dim",
        )
    else:
        _field(
            text,
            "Name",
            present_agent_name(entry.agent_local_name or entry.agent or "unknown"),
        )
        _field(
            text,
            "Status",
            None if detail is None else detail.agent_status,
        )
        dismissed = (
            None
            if detail is None or detail.dismissed is None
            else ("yes" if detail.dismissed else "no")
        )
        _field(text, "Dismissed", dismissed)
        _field(text, "Artifact", entry.agent_artifact_dir)

    if detail is not None and (
        detail.xprompt_prompt is not None or detail.rendered_prompt is not None
    ):
        _heading(text, "PROMPTS")
        _prompt_rendering_section(text, "XPrompt prompt", detail.xprompt_prompt)
        _prompt_rendering_section(text, "rendered prompt", detail.rendered_prompt)

    _heading(text, "TRANSCRIPT")
    if detail is None:
        text.append(
            "Loading transcript preview…\n" if loading else "Preview unavailable.\n",
            style="dim",
        )
    else:
        text.append(detail.transcript_preview or "_Empty transcript._", style="dim")
        text.append("\n")
        if detail.transcript_truncated:
            text.append(
                "… (truncated, press enter for the full chat)\n",
                style=f"italic {ARTIFACTS_ACCENTS['chats']}",
            )
    return text


def _provenance_section(
    text: Text,
    entry: ChatCatalogEntry,
    diagnostics: tuple[str, ...],
) -> None:
    color = CHAT_PROVENANCE_COLORS[entry.provenance]
    glyph = CHAT_PROVENANCE_GLYPHS[entry.provenance]
    label = (
        entry.source_machine or "remote"
        if entry.provenance == "remote"
        else entry.provenance
    )
    text.append(f"{glyph} {label}\n", style=f"bold {color}")
    if entry.provenance == "local":
        text.append("Only on this machine. Not published to the agents sidecar.\n")
    elif entry.provenance == "shared":
        text.append("From this machine; also published to the agents sidecar.\n")
        _field(text, "Sidecar repo", entry.sidecar_repo)
        _field(text, "Published chat", entry.sidecar_relpath)
    elif entry.provenance == "remote":
        owner = (
            "@".join(
                value
                for value in (entry.source_username, entry.source_machine)
                if value
            )
            or "another machine"
        )
        text.append(f"Pulled in from {owner} when the agents sidecar was synced.\n")
        _field(text, "Sidecar repo", entry.sidecar_repo)
        _field(text, "Global name", entry.agent_global_name)
        _field(text, "Imported path", entry.absolute_path)
    else:
        diagnostic = diagnostics[0] if diagnostics else "sidecar data was unavailable"
        text.append(f"Sync state unknown — {diagnostic}.\n")
    if entry.provenance in {"local", "shared"}:
        _publication_section(text, entry)


def _publication_section(text: Text, entry: ChatCatalogEntry) -> None:
    disposition = entry.publication_disposition
    if disposition is None:
        if entry.publication_pending and entry.publication_quarantined:
            disposition = "mixed"
        elif entry.publication_pending:
            disposition = "queued"
        elif entry.publication_quarantined:
            disposition = "quarantined"
    if disposition == "queued":
        message = (
            "Committed sidecar chat exists; publication completion remains queued"
            if entry.provenance == "shared"
            else "Queued to publish"
        )
        text.append(message, style="bold #FFD75F")
        _publication_diagnostics(text, entry, color="#FFD75F")
    elif disposition == "quarantined":
        message = (
            "Committed sidecar chat exists; publication retry is quarantined"
            if entry.provenance == "shared"
            else "Publication quarantined"
        )
        text.append(message, style="bold #FFAF5F")
        _publication_diagnostics(text, entry, color="#FFAF5F")
        text.append(
            "Run `sase agent sync --retry-quarantined` to retry.\n",
            style="#FFAF5F",
        )
    elif disposition == "retired":
        message = (
            "Committed sidecar chat exists; publication was retired as unpublishable"
            if entry.provenance == "shared"
            else "Publication retired as unpublishable"
        )
        text.append(message, style="bold #FF8787")
        _publication_diagnostics(text, entry, color="#FF8787")
        text.append(
            "Retrying cannot help; run `sase agent sync --drop-retired` to "
            "drop the request.\n",
            style="#FF8787",
        )
    elif disposition == "mixed":
        text.append(
            "Publication state mixed: retryable, quarantined, and retired "
            "requests coexist",
            style="bold #FFAF5F",
        )
        _publication_diagnostics(text, entry, color="#FFAF5F")
        text.append(
            "Active requests will retry automatically; run "
            "`sase agent sync --retry-quarantined` to release quarantined "
            "requests and `sase agent sync --drop-retired` to drop retired "
            "ones.\n",
            style="#FFAF5F",
        )


def _publication_diagnostics(
    text: Text,
    entry: ChatCatalogEntry,
    *,
    color: str,
) -> None:
    if entry.publication_attempts is not None:
        noun = "attempt" if entry.publication_attempts == 1 else "attempts"
        text.append(
            f" — {entry.publication_attempts} {noun}",
            style=color,
        )
    if entry.publication_last_error:
        text.append(
            f", last error: {entry.publication_last_error}",
            style=color,
        )
    text.append("\n")


def _heading(text: Text, label: str) -> None:
    if text:
        text.append("\n")
    text.append(
        f"{label}\n",
        style=f"bold underline {ARTIFACTS_ACCENTS['chats']}",
    )


def _field(text: Text, label: str, value: object | None) -> None:
    if value is None or value == "":
        return
    text.append(f"{label}: ", style="bold #87AFFF")
    text.append(f"{value}\n")


def _prompt_rendering_section(
    text: Text,
    label: str,
    value: str | None,
) -> None:
    if value is None:
        return
    text.append(f"{label}\n", style="bold #87AFFF")
    preview, truncated = _line_preview(value, _PROMPT_RENDERING_PREVIEW_LINES)
    text.append(preview or "_Empty prompt._", style="dim")
    text.append("\n")
    if truncated:
        text.append(
            "... (truncated, press enter for the full chat)\n",
            style=f"italic {ARTIFACTS_ACCENTS['chats']}",
        )


def chat_reference(path: str) -> str | None:
    """Canonicalize a transcript path without loading unrelated project context."""

    context = ArtifactRefContext(
        document_roots=(),
        chats_root=sase_subdir("chats").expanduser().resolve(strict=False),
        artifact_index_path=Path(),
        repositories=(),
        projects=(),
    )
    return reference_for_entry_target(
        "chats",
        ("chat", path),
        context=context,
    )


def _read_transcript_preview(
    path: Path,
) -> tuple[str, bool, StoredPromptRenderings]:
    lines: list[str] = []
    section_blocks: list[str] = []
    section_lines: list[str] = []
    active_section_end: str | None = None
    truncated = False
    try:
        with path.open("r", encoding="utf-8", errors="replace") as handle:
            for line in handle:
                stripped = line.strip()
                if active_section_end is not None:
                    section_lines.append(line)
                    if stripped == active_section_end:
                        section_blocks.append("".join(section_lines))
                        section_lines = []
                        active_section_end = None
                    continue
                if stripped == XPROMPT_SECTION_START:
                    section_lines = [line]
                    active_section_end = XPROMPT_SECTION_END
                    continue
                if stripped == RENDERED_SECTION_START:
                    section_lines = [line]
                    active_section_end = RENDERED_SECTION_END
                    continue
                if len(lines) >= _TRANSCRIPT_PREVIEW_LINES:
                    truncated = True
                    continue
                lines.append(line)
    except OSError:
        return "", False, StoredPromptRenderings()
    return (
        "".join(lines).rstrip(),
        truncated,
        extract_prompt_renderings("".join(section_blocks)),
    )


def _line_preview(content: str, limit: int) -> tuple[str, bool]:
    lines = content.splitlines(keepends=True)
    if len(lines) <= limit:
        return content.rstrip(), False
    return "".join(lines[:limit]).rstrip(), True


def _snippet_fallback(entry: ChatCatalogEntry) -> str:
    lines: list[str] = []
    if entry.prompt_snippet:
        lines.extend(("## Prompt", "", entry.prompt_snippet, ""))
    if entry.response_snippet:
        lines.extend(("## Response", "", entry.response_snippet))
    return "\n".join(lines).rstrip() or entry.basename


def _read_mapping(path: Path) -> dict[str, object]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return dict(value) if isinstance(value, Mapping) else {}


def _first_text(
    meta: Mapping[str, object],
    done: Mapping[str, object],
    *,
    keys: tuple[str, ...],
) -> str | None:
    for source in (meta, done):
        for key in keys:
            value = source.get(key)
            if isinstance(value, str) and value:
                return value
    return None


def _is_dismissed(entry: ChatCatalogEntry) -> bool:
    try:
        from sase.ace.dismissed_agents import load_dismissed_agents

        artifact_name = Path(entry.agent_artifact_dir or "").name
        return any(
            raw_suffix == artifact_name
            for _agent_type, _cl_name, raw_suffix in load_dismissed_agents()
        )
    except (ImportError, OSError, TypeError, ValueError):
        return False


def _format_size(size: int) -> str:
    if size < 1024:
        return f"{size} B"
    if size < 1024 * 1024:
        return f"{size / 1024:.1f} KiB"
    return f"{size / (1024 * 1024):.1f} MiB"


__all__ = [
    "ChatDetailData",
    "build_chat_detail",
    "load_chat_detail",
    "read_full_chat",
]
