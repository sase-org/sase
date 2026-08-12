"""Render canonical prompt documents from launch-time staging records."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

from sase.core.prompt_artifact_staging import PromptArtifactRecord
from sase.core.rust import require_rust_binding
from sase.sdd.plan_header_block import (
    PlanHeaderEntry,
    PlanHeaderSection,
    PlanHeaderSectionKind,
    upsert_plan_header_section,
)

ArtifactTargetResolver = Callable[[PromptArtifactRecord], str | None]


@dataclass(frozen=True, slots=True)
class RenderedPromptArchive:
    """One rendered prompt plus exactly the records linked from it."""

    document: str
    linked_records: tuple[PromptArtifactRecord, ...]
    reference_labels: tuple[Mapping[str, str], ...]


def load_manifest_records(
    manifest_path: Path,
    agent_artifacts_dir: Path | str,
) -> tuple[PromptArtifactRecord, ...]:
    """Parse and select the manifest rows belonging to one agent run."""

    if not manifest_path.is_file():
        return ()
    parse = require_rust_binding("prompt_artifact_manifest_parse")
    select = require_rust_binding("prompt_artifact_manifest_select")
    parsed = parse(manifest_path.read_bytes())
    selected = select(parsed, str(Path(agent_artifacts_dir).resolve(strict=False)))
    return tuple(cast(Sequence[PromptArtifactRecord], selected))


def render_prompt_document(
    prompt: str,
    records: Sequence[PromptArtifactRecord],
    *,
    artifact_target: ArtifactTargetResolver,
    agent_label: str,
    agent_target: str | None,
    plan_label: str | None = None,
    plan_target: str | None = None,
) -> RenderedPromptArchive:
    """Rewrite live refs and apply canonical PLAN/AGENTS/ARTIFACTS sections."""

    targets: dict[tuple[str, str | None, str], str | None] = {}

    def resolve_target(record: PromptArtifactRecord) -> str | None:
        key = (
            record["raw_ref"],
            record.get("sha256"),
            record["recorded_at"],
        )
        if key not in targets:
            targets[key] = artifact_target(record)
        return targets[key]

    rewrite = require_rust_binding("prompt_artifact_rewrite_links")
    payload = cast(
        Mapping[str, Any],
        rewrite(prompt, list(records), resolve_target),
    )
    linked = tuple(
        cast(Sequence[PromptArtifactRecord], payload.get("linked_records", ()))
    )
    reference_labels = tuple(
        cast(Sequence[Mapping[str, str]], payload.get("reference_labels", ()))
    )
    document = str(payload.get("prompt") or "")
    if plan_label is not None and plan_target is not None:
        from sase.sdd.artifact_links import (
            SddArtifactLinkType,
            update_cross_repository_artifact_link,
        )

        document = update_cross_repository_artifact_link(
            document,
            SddArtifactLinkType.PLAN,
            label=plan_label,
            href=plan_target,
        )
    document = upsert_plan_header_section(
        document,
        PlanHeaderSection(
            kind=PlanHeaderSectionKind.AGENTS,
            entries=(PlanHeaderEntry(label=agent_label, target=agent_target),),
        ),
    )
    artifact_entries = tuple(
        PlanHeaderEntry(label=record["label"], target=resolve_target(record))
        for record in linked
    )
    if artifact_entries:
        document = upsert_plan_header_section(
            document,
            PlanHeaderSection(
                kind=PlanHeaderSectionKind.ARTIFACTS,
                entries=artifact_entries,
            ),
        )

    from sase.file_references import format_with_prettier

    return RenderedPromptArchive(
        document=format_with_prettier(document),
        linked_records=linked,
        reference_labels=reference_labels,
    )


__all__ = [
    "ArtifactTargetResolver",
    "RenderedPromptArchive",
    "load_manifest_records",
    "render_prompt_document",
]
