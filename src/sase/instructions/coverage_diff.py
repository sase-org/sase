"""Intended-vs-observed section diff for one session and manifest."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sase.instructions import run_index as runs
from sase.instructions.coverage_records import ManifestRecord, matching_manifests
from sase.instructions.coverage_sessions import RootSession


def _strip_heading(section_text: str) -> str:
    """Return *section_text* without its first (heading) line."""
    _, _, rest = section_text.partition("\n")
    return rest


def _bundle_section_text(
    artifact_dir: str, record: ManifestRecord, *, bundle_text: str | None = None
) -> dict[str, str]:
    """Map included section id to body text from the run bundle file."""
    from sase.instructions.manifests import read_run_manifests

    texts: dict[str, str] = {}
    if bundle_text is None:
        for entry in read_run_manifests(artifact_dir):
            if entry.manifest is None or entry.bundle_path is None:
                continue
            facts = entry.manifest.get("facts")
            provider = ""
            if isinstance(facts, dict) and isinstance(facts.get("provider"), str):
                provider = str(facts["provider"]).lower()
            if provider != record.provider or entry.seq != record.seq:
                continue
            try:
                bundle_text = entry.bundle_path.read_text(encoding="utf-8")
            except OSError:
                return {}
            break
    if bundle_text is None:
        return {}
    sections = record.manifest.get("sections")
    if not isinstance(sections, list):
        return {}
    blob = bundle_text.encode("utf-8")
    for section in sections:
        if not isinstance(section, dict) or section.get("status") != "included":
            continue
        section_id = section.get("id")
        offset = section.get("offset")
        length = section.get("length")
        if (
            not isinstance(section_id, str)
            or not isinstance(offset, int)
            or not isinstance(length, int)
        ):
            continue
        try:
            texts[section_id] = blob[offset : offset + length].decode("utf-8")
        except (ValueError, UnicodeDecodeError):
            continue
    return texts


def loaded_source_texts(
    provider: str, run: runs.ScoredRun, session_id: str
) -> tuple[list[str], list[str]]:
    """Return ``(native, explicit)`` loaded source texts for one session.

    Session files are read only when a diff is requested; the plain
    scoreboard path never calls this.
    """
    from sase.instructions import claude as claude_parser
    from sase.instructions import codex as codex_parser
    from sase.instructions import grok as grok_parser
    from sase.instructions import muse as muse_parser
    from sase.llm_provider._muse_session_usage import find_muse_session_log

    if provider == "claude":
        return _claude_texts(claude_parser, run, session_id)
    if provider == "codex":
        return _codex_texts(codex_parser, run, session_id)
    if provider == "grok":
        return _grok_texts(grok_parser, run, session_id)
    if provider == "muse":
        return _muse_texts(muse_parser, find_muse_session_log, session_id)
    return [], []


def _claude_texts(
    claude_parser: Any, run: runs.ScoredRun, session_id: str
) -> tuple[list[str], list[str]]:
    candidate = runs.claude_project_dir(run.workspace_dir) / f"{session_id}.jsonl"
    records: list[dict[str, Any]] = []
    if candidate.is_file():
        records, _ = runs.read_jsonl_capped(
            candidate, max_bytes=runs.ROOT_TRANSCRIPT_BYTE_CAP
        )
    files = claude_parser.instruction_files(records)
    native = [entry["content"] for entry in files]
    snapshot = claude_parser.system_prompt_text(records)
    return native, [snapshot] if snapshot else []


def _codex_texts(
    codex_parser: Any, run: runs.ScoredRun, session_id: str
) -> tuple[list[str], list[str]]:
    records: list[dict[str, Any]] = []
    for path in runs.find_codex_sessions(run):
        if path.stem == session_id:
            records, _ = runs.read_jsonl_capped(
                path, max_bytes=runs.ROOT_TRANSCRIPT_BYTE_CAP
            )
            break
    native = codex_parser.block_sources(codex_parser.agents_blocks(records))
    explicit = codex_parser.developer_texts(records)
    return native, explicit


def _grok_texts(
    grok_parser: Any, run: runs.ScoredRun, session_id: str
) -> tuple[list[str], list[str]]:
    session_dir: Path | None = None
    for child in runs.find_grok_sessions(run):
        if child.name == session_id:
            session_dir = child
            break
    if session_dir is None:
        return [], []
    context = runs.read_json_object(session_dir / "prompt_context.json")
    system_prompt, _ = runs.read_text_capped(
        session_dir / "system_prompt.txt", max_bytes=runs.ROOT_TRANSCRIPT_BYTE_CAP
    )
    native: list[str] = []
    raw_agents = context.get("agents_md_files", [])
    if isinstance(raw_agents, list):
        for entry in raw_agents:
            if isinstance(entry, dict) and isinstance(entry.get("content"), str):
                native.append(str(entry["content"]))
            elif isinstance(entry, str):
                native.append(entry)
    rules = grok_parser.human_rules_block(system_prompt)
    return native, [rules] if rules else []


def _muse_texts(
    muse_parser: Any, find_log: Any, session_id: str
) -> tuple[list[str], list[str]]:
    log_path = find_log(session_id)
    if log_path is None:
        return [], []
    records, _ = runs.read_jsonl_capped(
        log_path, max_bytes=runs.ROOT_TRANSCRIPT_BYTE_CAP
    )
    native = muse_parser.rules_texts(records)
    explicit = muse_parser.prompt_texts(records)
    return native, explicit


@dataclass(frozen=True)
class SectionDiffRow:
    """One intended-vs-observed section row."""

    id: str
    layer: str
    observed: int
    native: int
    explicit: int


@dataclass(frozen=True)
class SectionDiff:
    """Intended-vs-observed diff for one session and manifest."""

    session_id: str
    run_name: str
    manifest_path: str | None
    purpose: str | None
    unavailable: bool
    rows: tuple[SectionDiffRow, ...] = ()


def section_diff_for_session(
    session: RootSession,
    run: runs.ScoredRun,
    records: list[ManifestRecord],
    *,
    partial: bool = False,
    bundle_text: str | None = None,
) -> SectionDiff:
    """Diff *session*'s loaded sources against its matching manifest."""
    from sase.instructions import fingerprints as fp

    matches = matching_manifests(session, records)
    if session.provider == "agy" or not matches:
        return SectionDiff(
            session_id=session.session_id,
            run_name=session.run_name,
            manifest_path=None,
            purpose=None,
            unavailable=True,
        )
    record = matches[0]
    section_texts = _bundle_section_text(
        session.artifact_dir, record, bundle_text=bundle_text
    )
    native, explicit = loaded_source_texts(session.provider, run, session.session_id)
    flat_native = [fp.flatten_ws(text) for text in native]
    flat_explicit = [fp.flatten_ws(text) for text in explicit]
    sections = record.manifest.get("sections")
    layer_by_id: dict[str, str] = {}
    if isinstance(sections, list):
        for section in sections:
            if (
                isinstance(section, dict)
                and isinstance(section.get("id"), str)
                and isinstance(section.get("layer"), str)
            ):
                layer_by_id[str(section["id"])] = str(section["layer"])
    rows: list[SectionDiffRow] = []
    for section_id, body in sorted(section_texts.items()):
        layer = layer_by_id.get(section_id, "")
        if layer == "frame":
            continue
        flat_body = fp.flatten_ws(_strip_heading(body)).strip()
        if not flat_body:
            continue
        native_hits = sum(1 for text in flat_native if flat_body in text)
        explicit_hits = sum(1 for text in flat_explicit if flat_body in text)
        rows.append(
            SectionDiffRow(
                id=section_id,
                layer=layer,
                observed=0 if partial else native_hits + explicit_hits,
                native=0 if partial else native_hits,
                explicit=0 if partial else explicit_hits,
            )
        )
    return SectionDiff(
        session_id=session.session_id,
        run_name=session.run_name,
        manifest_path=record.manifest_path or None,
        purpose=record.purpose or None,
        unavailable=partial,
        rows=tuple(rows),
    )


__all__ = [
    "SectionDiff",
    "SectionDiffRow",
    "loaded_source_texts",
    "section_diff_for_session",
]
