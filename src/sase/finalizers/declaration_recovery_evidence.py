"""Bounded evidence brief for a finalizer declaration-recovery turn."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import TYPE_CHECKING

from sase.finalizers.declaration_store import load_accepted_host_repositories
from sase.llm_provider.commit_finalizer_baseline import load_dirty_baseline
from sase.llm_provider.commit_finalizer_git import normalize_path

if TYPE_CHECKING:
    from sase.core.finalizer_wire import FinalizerObligationWire
    from sase.finalizers.declaration import FinalContextPublication
    from sase.llm_provider.commit_finalizer_baseline import DirtyBaseline

_logger = logging.getLogger(__name__)

_PROMPT_CHAR_LIMIT = 2000
_RESPONSE_CHAR_LIMIT = 4000
_MAX_PATHS_PER_REPO = 100
_MAX_TOOL_CALL_PATHS = 100
_WRITE_TOOL_NAMES = frozenset({"Edit", "Write", "NotebookEdit"})
_TOOL_CALLS_FILENAME = "tool_calls.jsonl"

_LABEL_NEW = "new since run start"
_LABEL_CHANGED = "changed since run start"
_LABEL_UNKNOWN = "provenance unknown"

_OWN_WORK_STATEMENT = (
    "The host snapshotted dirty paths before the first turn. "
    "`collect_dirty_state` already subtracts every path that is provably "
    "unchanged since that snapshot. Each listed path is therefore this "
    "run's own work, not another agent's in-flight edit."
)
_HEDGED_STATEMENT = (
    "No run-start baseline was captured, so the host cannot rule out "
    "pre-existing dirt. Inspect the diff before deciding."
)


def build_recovery_evidence(
    *,
    context: FinalContextPublication,
    original_prompt: str | None,
    response_text: str,
    artifacts_dir: str | None,
) -> str:
    """Render the host's bounded, best-effort brief for a recovery turn."""

    try:
        return _build_recovery_evidence_body(
            context=context,
            original_prompt=original_prompt,
            response_text=response_text,
            artifacts_dir=artifacts_dir,
        )
    except Exception:
        _logger.warning(
            "Failed to build finalizer declaration-recovery evidence brief",
            exc_info=True,
        )
        return ""


def _build_recovery_evidence_body(
    *,
    context: FinalContextPublication,
    original_prompt: str | None,
    response_text: str,
    artifacts_dir: str | None,
) -> str:
    root = _artifacts_root(artifacts_dir)
    baseline = load_dirty_baseline(root) if root is not None else None
    host_paths = _host_paths_by_obligation(root)
    sections: list[str] = []

    prompt_section = _prompt_section(original_prompt)
    if prompt_section is not None:
        sections.append(prompt_section)

    response_section = _response_section(response_text)
    if response_section is not None:
        sections.append(response_section)

    repo_obligations = tuple(
        obligation
        for obligation in context.context.obligations
        if obligation.kind == "repository" and obligation.paths
    )
    if repo_obligations:
        sections.append(
            _paths_section(
                repo_obligations,
                host_paths=host_paths,
                baseline=baseline,
            )
        )
        sections.append(_provenance_section(baseline is not None))

    written_section = _written_files_section(root)
    if written_section is not None:
        sections.append(written_section)

    return "\n\n".join(sections)


def _artifacts_root(artifacts_dir: str | None) -> Path | None:
    if not artifacts_dir:
        return None
    root = Path(artifacts_dir)
    if root.exists() and not root.is_dir():
        raise OSError(f"artifacts dir is not a directory: {root}")
    return root


def _host_paths_by_obligation(root: Path | None) -> dict[str, str]:
    if root is None:
        return {}
    try:
        records = load_accepted_host_repositories(root)
    except Exception:
        return {}
    return {record.obligation_id: record.path for record in records}


def _prompt_section(original_prompt: str | None) -> str | None:
    text = original_prompt.strip() if original_prompt else ""
    if not text:
        return None
    return "## What this run was asked to do\n\n" + _truncate_head(
        text, _PROMPT_CHAR_LIMIT
    )


def _response_section(response_text: str) -> str | None:
    text = response_text.strip() if response_text else ""
    if not text:
        return None
    return "## What this run reported doing before it stopped\n\n" + _truncate_tail(
        text, _RESPONSE_CHAR_LIMIT
    )


def _paths_section(
    obligations: tuple[FinalizerObligationWire, ...],
    *,
    host_paths: dict[str, str],
    baseline: DirtyBaseline | None,
) -> str:
    blocks: list[str] = ["## Uncommitted paths the host is asking you to decide about"]
    for obligation in obligations:
        display = obligation.display_name or obligation.obligation_id
        repo_path = host_paths.get(obligation.obligation_id)
        labels = [
            _path_provenance(
                repo_path=repo_path,
                rel_path=rel_path,
                baseline=baseline,
            )
            for rel_path in obligation.paths
        ]
        blocks.append(f"### {display}")
        blocks.append(_render_capped_path_lines(obligation.paths, labels))
    return "\n\n".join(blocks)


def _path_provenance(
    *,
    repo_path: str | None,
    rel_path: str,
    baseline: DirtyBaseline | None,
) -> str:
    if baseline is None or repo_path is None:
        return _LABEL_UNKNOWN
    fingerprints = baseline.get(normalize_path(repo_path))
    if fingerprints is None:
        return _LABEL_NEW
    if rel_path in fingerprints:
        return _LABEL_CHANGED
    return _LABEL_NEW


def _render_capped_path_lines(paths: list[str], labels: list[str]) -> str:
    lines = [f"- `{path}` — {label}" for path, label in zip(paths, labels, strict=True)]
    return _cap_lines(lines, _MAX_PATHS_PER_REPO)


def _provenance_section(baseline_available: bool) -> str:
    statement = _OWN_WORK_STATEMENT if baseline_available else _HEDGED_STATEMENT
    return "## How the host knows whose changes these are\n\n" + statement


def _written_files_section(root: Path | None) -> str | None:
    if root is None:
        return None
    paths = _written_paths_from_tool_calls(root)
    if not paths:
        return None
    lines = [f"- `{path}`" for path in paths]
    return "## Files this run wrote directly\n\n" + _cap_lines(
        lines, _MAX_TOOL_CALL_PATHS
    )


def _written_paths_from_tool_calls(root: Path) -> tuple[str, ...]:
    path = root / _TOOL_CALLS_FILENAME
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError:
        return ()
    seen: dict[str, None] = {}
    for line in raw.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        try:
            row = json.loads(stripped)
        except json.JSONDecodeError:
            continue
        if not isinstance(row, dict):
            continue
        if row.get("event") != "ToolUse":
            continue
        if row.get("tool_name") not in _WRITE_TOOL_NAMES:
            continue
        summary = row.get("tool_input_summary")
        if not isinstance(summary, dict):
            continue
        file_path = summary.get("file_path")
        if not isinstance(file_path, str) or not file_path:
            continue
        seen.setdefault(_workspace_relative(file_path), None)
    return tuple(seen)


def _workspace_relative(path: str) -> str:
    candidate = Path(path)
    if not candidate.is_absolute():
        return path
    try:
        return str(
            candidate.resolve(strict=False).relative_to(
                Path.cwd().resolve(strict=False)
            )
        )
    except ValueError:
        return path


def _truncate_head(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    shown = text[:limit]
    return f"{shown}\n{_truncation_marker(len(shown), len(text))}"


def _truncate_tail(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    shown = text[-limit:]
    return f"{_truncation_marker(len(shown), len(text))}\n{shown}"


def _cap_lines(lines: list[str], limit: int) -> str:
    if len(lines) <= limit:
        return "\n".join(lines)
    shown = lines[:limit]
    shown_text = "\n".join(shown)
    full_text = "\n".join(lines)
    return f"{shown_text}\n{_truncation_marker(len(shown_text), len(full_text))}"


def _truncation_marker(shown: int, total: int) -> str:
    return f"… (truncated; showing {shown} of {total} characters)"
