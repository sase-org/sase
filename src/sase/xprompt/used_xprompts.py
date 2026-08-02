"""Capture xprompt references used by an agent prompt."""

from __future__ import annotations

import json
import os
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, TypedDict

from sase.xprompt._literal_zones import literal_zone_ranges
from sase.xprompt._parsing import (
    XPromptReference,
    iter_xprompt_references,
    normalize_vcs_underscore_refs,
)
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
    kind: Literal["workflow", "part", "swarm"]
    positional: list[str]
    named: dict[str, str]
    tags: list[str]


@dataclass(frozen=True)
class _ScannedXPromptReference:
    """One launch reference produced by the shared xprompt scan."""

    raw_ref: str
    name: str
    kind: Literal["workflow", "part", "swarm"] | None
    item: XPrompt | Workflow | None
    reference: XPromptReference | None


def encode_launch_swarm_xprompts(names: Sequence[str]) -> str:
    """Encode launch-boundary swarm provenance for a child process."""
    return json.dumps(list(names), separators=(",", ":"))


def scan_xprompt_references(
    raw_prompt: str,
    *,
    extra_xprompts: dict[str, XPrompt] | None = None,
    swarm_xprompts: Sequence[str] | None = None,
) -> list[_ScannedXPromptReference]:
    """Return known and unknown references using the launch lexical contract.

    This is the single scan shared by usage metadata and definition provenance.
    ``raw_ref`` is sliced from the alias-resolved prompt that survives as
    ``raw_xprompt.md``; VCS underscore normalization is applied only to the
    parsing copy so tokens such as ``#gh_sase`` retain their exact spelling.
    """
    swarm_names = tuple(dict.fromkeys(swarm_xprompts or ()))
    if "#" not in raw_prompt and not swarm_names:
        return []

    prompt = resolve_xprompt_aliases(raw_prompt)
    if "#" not in prompt and not swarm_names:
        return []

    normalized_prompt = normalize_vcs_underscore_refs(prompt)
    ignored_ranges = literal_zone_ranges(normalized_prompt)

    workflows = get_all_workflows()
    xprompts = get_all_xprompts()
    if extra_xprompts:
        xprompts = {**xprompts, **extra_xprompts}

    scanned: list[_ScannedXPromptReference] = []
    for ref in iter_xprompt_references(normalized_prompt):
        if _in_ignored_range(ref.start, ignored_ranges):
            continue
        resolved = _resolve_reference(ref.name, workflows, xprompts)
        kind, item = resolved if resolved is not None else (None, None)
        raw_ref = prompt[ref.start : ref.end]
        if len(raw_ref) != len(ref.raw):
            # Alias resolution precedes both strings and VCS normalization is
            # length-preserving, but retain a safe fallback if that contract
            # ever changes.
            raw_ref = ref.raw
        scanned.append(
            _ScannedXPromptReference(
                raw_ref=raw_ref,
                name=ref.name,
                kind=kind,
                item=item,
                reference=ref,
            )
        )

    swarm_records = [
        _ScannedXPromptReference(
            raw_ref=f"#{name}",
            name=name,
            kind="swarm",
            item=xprompts.get(name),
            reference=None,
        )
        for name in swarm_names
    ]
    if not swarm_records:
        return scanned

    swarm_name_set = set(swarm_names)
    return swarm_records + [
        record for record in scanned if record.name not in swarm_name_set
    ]


def collect_used_xprompts(
    raw_prompt: str,
    *,
    extra_xprompts: dict[str, XPrompt] | None = None,
    swarm_xprompts: Sequence[str] | None = None,
) -> list[_UsedXPromptRecord]:
    """Return known top-level xprompt references from *raw_prompt*.

    The scan uses the shared lexical xprompt reference parser, after applying
    the same alias and VCS-underscore normalization used by expansion. Fenced
    code blocks and disabled xprompt regions are protected before scanning.
    Launch-boundary swarm provenance is prepended and supersedes any lexical
    records with the same name.
    """
    records: list[_UsedXPromptRecord] = []
    seen: set[tuple[str, str, tuple[str, ...], tuple[tuple[str, str], ...]]] = set()
    for scanned in scan_xprompt_references(
        raw_prompt,
        extra_xprompts=extra_xprompts,
        swarm_xprompts=swarm_xprompts,
    ):
        if scanned.kind is None or (scanned.item is None and scanned.kind != "swarm"):
            continue
        if scanned.kind == "swarm":
            positional: list[str] = []
            named: dict[str, str] = {}
        elif scanned.kind == "workflow":
            assert scanned.reference is not None
            positional, named = parse_workflow_reference_args(scanned.reference)
        else:
            assert scanned.reference is not None
            positional, named = scanned.reference.parse_arguments()

        key = (
            scanned.name,
            scanned.kind,
            tuple(positional),
            tuple(sorted(named.items())),
        )
        if key in seen:
            continue
        seen.add(key)

        records.append(
            {
                "name": scanned.name,
                "kind": scanned.kind,
                "positional": positional,
                "named": named,
                "tags": (
                    sorted(tag.value for tag in scanned.item.tags)
                    if scanned.item is not None
                    else []
                ),
            }
        )
    return records


def write_used_xprompts(
    artifacts_dir: str | os.PathLike[str] | None,
    raw_prompt: str,
    step_name: str | None = None,
    *,
    extra_xprompts: dict[str, XPrompt] | None = None,
    swarm_xprompts: Sequence[str] | None = None,
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
    records = collect_used_xprompts(
        raw_prompt,
        extra_xprompts=extra_xprompts,
        swarm_xprompts=swarm_xprompts,
    )
    if not records or artifacts_dir is None:
        return records

    artifacts_path = Path(artifacts_dir)
    if not artifacts_path.is_dir():
        return records

    if step_name:
        step_records = (
            collect_used_xprompts(raw_prompt, extra_xprompts=extra_xprompts)
            if swarm_xprompts
            else records
        )
        if step_records:
            _write_json(artifacts_path / f"xprompts_{step_name}.json", step_records)

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
