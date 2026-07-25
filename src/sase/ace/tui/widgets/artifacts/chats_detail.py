"""Off-thread detail loading and Rich rendering for Artifacts Chats."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
import json
from pathlib import Path

from rich.text import Text

from sase.core.agent_identity_facade import present_agent_name
from sase.history.chat_catalog_provenance import ChatCatalogEntry

from .chats_rendering import CHAT_PROVENANCE_COLORS, CHAT_PROVENANCE_GLYPHS
from .types import ARTIFACTS_ACCENTS

_TRANSCRIPT_PREVIEW_LINES = 200


@dataclass(frozen=True, slots=True)
class ChatDetailData:
    """Bounded transcript and agent facts loaded away from the event loop."""

    absolute_path: str
    transcript_preview: str
    transcript_truncated: bool
    model: str | None = None
    provider: str | None = None
    agent_status: str | None = None
    dismissed: bool | None = None


def load_chat_detail(entry: ChatCatalogEntry) -> ChatDetailData:
    """Read bounded transcript and artifact facts for one selected row."""

    preview, truncated = _read_transcript_preview(Path(entry.absolute_path))
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
    """Build all four detail sections from cached catalog/detail data."""

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
        if entry.publication_quarantined:
            text.append("Publication quarantined", style="bold #FFAF5F")
            _publication_diagnostics(text, entry, color="#FFAF5F")
            text.append(
                "Run `sase agent sync --retry-quarantined` to retry.\n",
                style="#FFAF5F",
            )
        elif entry.publication_pending:
            text.append("Queued to publish", style="bold #FFD75F")
            _publication_diagnostics(text, entry, color="#FFD75F")
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


def _read_transcript_preview(path: Path) -> tuple[str, bool]:
    lines: list[str] = []
    try:
        with path.open("r", encoding="utf-8", errors="replace") as handle:
            for index, line in enumerate(handle):
                if index >= _TRANSCRIPT_PREVIEW_LINES:
                    return "".join(lines).rstrip(), True
                lines.append(line)
    except OSError:
        return "", False
    return "".join(lines).rstrip(), False


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
