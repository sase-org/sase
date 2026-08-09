"""Prompt scanning helpers for launch-prompt artifact references."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
import sys

from sase.artifact_ref_models import ArtifactRefContext, ArtifactRefSpan
from sase.xprompt.input_binding import InputBindingError, bind_input_args
from sase.xprompt.models import XPrompt


@dataclass(frozen=True, slots=True)
class ArtifactRefFailure:
    reference: str
    status: str
    detail: str | None = None


class ArtifactRefRendererError(RuntimeError):
    """Raised when the selected ref renderer cannot render."""


@dataclass(frozen=True, slots=True)
class RefRewrite:
    start: int
    replacement: str
    raw: str


def rewrite_ref_xprompt_references(
    prompt: str,
    *,
    context: ArtifactRefContext,
    ref_renderers: Mapping[str, XPrompt],
) -> tuple[str, dict[int, RefRewrite]]:
    """Rewrite ``#ref/kind`` renderer calls into scanner-readable refs."""

    from sase.xprompt._literal_zones import literal_zone_ranges
    from sase.xprompt._parsing import iter_xprompt_references

    literal_ranges = literal_zone_ranges(prompt)
    replacements: list[tuple[int, int, str, str]] = []
    failures: list[ArtifactRefFailure] = []
    known_kinds = set(context.known_kinds)
    for reference in iter_xprompt_references(prompt):
        if not reference.name.startswith("ref/"):
            continue
        if overlaps_any(reference.start, reference.end, literal_ranges):
            continue

        kind = reference.name.removeprefix("ref/")
        renderer = ref_renderers.get(reference.name)
        if kind not in known_kinds or renderer is None:
            failures.append(
                ArtifactRefFailure(
                    reference.raw,
                    "unknown_kind",
                    f"unknown artifact reference kind: {kind}",
                )
            )
            continue
        try:
            payload = _bind_ref_xprompt_argument(renderer, reference.raw)
        except InputBindingError as exc:
            failures.append(ArtifactRefFailure(reference.raw, "invalid", str(exc)))
            continue
        replacements.append(
            (reference.start, reference.end, f"@{kind}:{payload}", reference.raw)
        )

    if failures:
        print_artifact_ref_failures(failures)
        sys.exit(1)
    if not replacements:
        return prompt, {}

    chunks: list[str] = []
    rewrites: dict[int, RefRewrite] = {}
    cursor = 0
    for start, end, replacement, raw in sorted(replacements):
        chunks.append(prompt[cursor:start])
        replacement_start = sum(len(chunk) for chunk in chunks)
        chunks.append(replacement)
        rewrites[replacement_start] = RefRewrite(
            start=replacement_start,
            replacement=replacement,
            raw=raw,
        )
        cursor = end
    chunks.append(prompt[cursor:])
    return "".join(chunks), rewrites


def _bind_ref_xprompt_argument(renderer: XPrompt, raw: str) -> str:
    from sase.xprompt._parsing import parse_workflow_reference

    if len(renderer.inputs) != 1:
        raise InputBindingError(
            f"ref renderer {renderer.name!r} must declare exactly one input"
        )
    input_arg = renderer.inputs[0]
    _name, positional_args, named_args = parse_workflow_reference(raw.removeprefix("#"))
    bound = bind_input_args(renderer.inputs, positional_args, named_args)
    unknown = sorted(set(bound.explicit_values).difference({input_arg.name}))
    if unknown:
        raise InputBindingError("unknown ref argument(s): " + ", ".join(unknown))
    if input_arg.name not in bound.explicit_values:
        raise InputBindingError(f"missing required argument: {input_arg.name}")
    return str(bound.values[input_arg.name])


def raw_candidate_text(
    candidate_text: str,
    start: int,
    rewrites: Mapping[int, RefRewrite],
) -> str:
    rewrite = rewrites.get(start)
    if rewrite is None:
        return candidate_text
    if candidate_text.startswith(rewrite.replacement):
        return rewrite.raw + candidate_text[len(rewrite.replacement) :]
    return rewrite.raw


def byte_to_character_offsets(text: str) -> dict[int, int]:
    offsets = {0: 0}
    byte_offset = 0
    for character_offset, character in enumerate(text, start=1):
        byte_offset += len(character.encode("utf-8"))
        offsets[byte_offset] = character_offset
    return offsets


def character_span(
    span: ArtifactRefSpan,
    *,
    byte_to_char: Mapping[int, int],
) -> tuple[int, int]:
    try:
        return byte_to_char[span.start], byte_to_char[span.end]
    except KeyError as exc:
        raise RuntimeError(
            "sase_core_rs returned an artifact-reference span outside UTF-8 "
            "character boundaries"
        ) from exc


def overlaps_any(
    start: int,
    end: int,
    ranges: list[tuple[int, int]],
) -> bool:
    return any(
        start < range_end and end > range_start for range_start, range_end in ranges
    )


def print_artifact_ref_failures(failures: list[ArtifactRefFailure]) -> None:
    print("\n❌ ERROR: The following artifact reference(s) could not be resolved:")
    for failure in failures:
        detail = f": {failure.detail}" if failure.detail else ""
        print(f"  - {failure.reference} ({failure.status}{detail})")
    print("\n⚠️ Artifact reference validation failed. Terminating workflow.\n")
