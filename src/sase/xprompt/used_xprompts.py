"""Capture xprompt references used by an agent prompt."""

from __future__ import annotations

import json
import os
from collections.abc import Sequence
from pathlib import Path
from typing import Any, Literal, TypedDict

from sase.xprompt._literal_zones import literal_zone_ranges
from sase.xprompt._parsing import iter_xprompt_references, normalize_vcs_underscore_refs
from sase.xprompt.loader import get_all_workflows, get_all_xprompts
from sase.xprompt.models import XPrompt
from sase.xprompt.processor import resolve_xprompt_aliases
from sase.xprompt.workflow_executor_steps_embedded_types import (
    parse_workflow_reference_args,
)
from sase.xprompt.workflow_models import Workflow

SASE_LAUNCH_SWARM_XPROMPTS = "SASE_LAUNCH_SWARM_XPROMPTS"


class _UsedXPromptRecord(TypedDict):
    name: str
    kind: Literal["workflow", "part"]
    positional: list[str]
    named: dict[str, str]
    tags: list[str]


def encode_launch_swarm_xprompts(names: Sequence[str]) -> str:
    """Encode launch-boundary swarm provenance for a child process."""
    return json.dumps(list(names), separators=(",", ":"))


def collect_used_xprompts(
    raw_prompt: str,
    *,
    extra_xprompts: dict[str, XPrompt] | None = None,
) -> list[_UsedXPromptRecord]:
    """Return known top-level xprompt references from *raw_prompt*.

    The scan uses the shared lexical xprompt reference parser, after applying
    the same alias and VCS-underscore normalization used by expansion. Fenced
    code blocks and disabled xprompt regions are protected before scanning.
    """
    if "#" not in raw_prompt:
        return []

    prompt = resolve_xprompt_aliases(raw_prompt)
    if "#" not in prompt:
        return []

    prompt = normalize_vcs_underscore_refs(prompt)
    ignored_ranges = literal_zone_ranges(prompt)

    workflows = get_all_workflows()
    xprompts = get_all_xprompts()
    if extra_xprompts:
        xprompts = {**xprompts, **extra_xprompts}

    records: list[_UsedXPromptRecord] = []
    seen: set[tuple[str, str, tuple[str, ...], tuple[tuple[str, str], ...]]] = set()

    for ref in iter_xprompt_references(prompt):
        if _in_ignored_range(ref.start, ignored_ranges):
            continue
        resolved = _resolve_reference(ref.name, workflows, xprompts)
        if resolved is None:
            continue
        kind, item = resolved
        if kind == "workflow":
            positional, named = parse_workflow_reference_args(ref)
        else:
            positional, named = ref.parse_arguments()

        key = (
            ref.name,
            kind,
            tuple(positional),
            tuple(sorted(named.items())),
        )
        if key in seen:
            continue
        seen.add(key)

        records.append(
            {
                "name": ref.name,
                "kind": kind,
                "positional": positional,
                "named": named,
                "tags": sorted(tag.value for tag in item.tags),
            }
        )

    return records


def write_used_xprompts(
    artifacts_dir: str | os.PathLike[str] | None,
    raw_prompt: str,
    step_name: str | None = None,
    *,
    extra_xprompts: dict[str, XPrompt] | None = None,
    step_only: bool = False,
) -> list[_UsedXPromptRecord]:
    """Collect and write xprompt metadata artifacts for *raw_prompt*.

    The shared ``xprompts.json`` holds launch/root metadata read by non-step
    agent rows; ``xprompts_<step>.json`` holds per-step metadata read by
    workflow-child rows.

    By default both files are written (the shared file, plus a step file when
    *step_name* is given), overwriting any existing copies. Pass
    ``step_only=True`` from prompt-step execution so the step writes its own
    ``xprompts_<step>.json`` but leaves an already-written shared
    ``xprompts.json`` (the launch-boundary metadata) untouched. When no shared
    file exists yet, a ``step_only`` write still seeds it so launch paths that
    do not capture usage at their own boundary keep populating root rows.
    """
    records = collect_used_xprompts(raw_prompt, extra_xprompts=extra_xprompts)
    if not records or artifacts_dir is None:
        return records

    artifacts_path = Path(artifacts_dir)
    if not artifacts_path.is_dir():
        return records

    if step_name:
        _write_json(artifacts_path / f"xprompts_{step_name}.json", records)

    shared_path = artifacts_path / "xprompts.json"
    if not (step_only and shared_path.exists()):
        _write_json(shared_path, records)

    return records


def _resolve_reference(
    name: str,
    workflows: dict[str, Workflow],
    xprompts: dict[str, XPrompt],
) -> tuple[Literal["workflow"], Workflow] | tuple[Literal["part"], XPrompt] | None:
    # Workflows intentionally win on collision, matching the embedded workflow
    # expansion contract for names present in both catalogs.
    if name in workflows:
        return "workflow", workflows[name]
    if name in xprompts:
        return "part", xprompts[name]
    return None


def _in_ignored_range(position: int, ranges: list[tuple[int, int]]) -> bool:
    return any(start <= position < end for start, end in ranges)


def _write_json(path: Path, records: list[_UsedXPromptRecord]) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(records, f, indent=2)
