"""Python instruction bundle compiler (E2 decisions 5-7).

Composes bundles from the structured memory units with fixed layers, section
ids, layout, and root/helper/interactive/export overlays; validates facts;
and assembles normalized manifests. Section assembly lives in
:mod:`sase.instructions.sections`. Only this module's miss path imports the
heavy composition modules; the cache-hit path stays on light imports.
"""

from __future__ import annotations

import hashlib
import time
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sase.instructions import cache as cache
from sase.instructions.facts import InstructionFacts, parse_facts
from sase.instructions.sections import (
    InstructionCompileError,
    SectionBuilder,
    assemble_sections,
    section_wire_dict,
)

#: Compiler identity recorded in every manifest (decision 13).
COMPILER_NAME = "sase-instructions"

#: Compiler version: hashed into the render-cache key and recorded in manifests.
COMPILER_VERSION = 1


@dataclass(frozen=True)
class CompiledBundle:
    """One compiled bundle: bytes plus its wire-shaped section table."""

    text: str
    sections: tuple[dict[str, Any], ...]
    sha256: str
    total_bytes: int
    total_lines: int
    tokens_est: int
    layers: dict[str, dict[str, int]]
    store_path: str
    render_ms: float
    cache: str


def _compile_uncached(
    facts: InstructionFacts, *, project_root: Path, home_root: Path
) -> tuple[str, list[SectionBuilder]]:
    """Compose bundle text and sections without touching the cache."""
    from sase.amd._config import resolve_amd_h1_title
    from sase.amd.memory_units import (
        ContractInputs,
        MemoryRootUnits,
        collect_memory_root_units,
    )
    from sase.main.init_memory.config import (
        linked_entries_from_config,
        project_config_read_path,
    )
    from sase.main.init_memory.root_planning import (
        memory_web_root_plan,
        retired_note_relative_paths,
    )
    from sase.main.init_memory.root_rendering_notes import (
        generated_long_notes,
        generated_short_notes,
        render_generated_project_long_memory_contents,
        render_generated_sase_memory_body,
    )
    from sase.memory.paths import CANONICAL_MEMORY_RELATIVE_ROOT, memory_read_root
    from sase.config.core import CHEZMOI_HOME, CONFIG_DIR, get_use_chezmoi

    if not project_root.is_dir():
        raise InstructionCompileError(
            f"project root {str(project_root)!r} is not a directory"
        )

    project_config = project_config_read_path(root=project_root)
    project_entries, project_errors = linked_entries_from_config(
        project_config,
        label="project",
        project_name=facts.project,
    )
    if project_errors:
        raise InstructionCompileError("; ".join(project_errors))
    if get_use_chezmoi():
        global_config = CHEZMOI_HOME / "dot_config" / "sase" / "sase.yml"
    else:
        global_config = CONFIG_DIR / "sase.yml"
    home_entries, home_errors = linked_entries_from_config(global_config, label="home")
    if home_errors:
        raise InstructionCompileError("; ".join(home_errors))

    merged_entries: list[Any] = list(project_entries)
    project_names = {entry.name for entry in project_entries}
    for entry in home_entries:
        if entry.name in project_names:
            continue
        project_names.add(entry.name)
        merged_entries.append(
            entry.__class__(
                name=entry.name,
                description=f"{entry.description} (home configuration)",
                path=entry.path,
                auto_clone=entry.auto_clone,
            )
        )

    template_body, template_error = render_generated_sase_memory_body(
        project_root, merged_entries, project_name=facts.project
    )
    if template_error is not None or template_body is None:
        raise InstructionCompileError(
            template_error or "failed to render the contract template"
        )

    project_title, project_title_error = resolve_amd_h1_title(
        project_root, derive_project_title=True
    )
    if project_title_error is not None:
        raise InstructionCompileError(project_title_error)
    home_title: str | None = None
    home_exists = home_root.is_dir()
    if home_exists:
        home_title, home_title_error = resolve_amd_h1_title(home_root)
        if home_title_error is not None:
            raise InstructionCompileError(home_title_error)

    short_notes = generated_short_notes(template_body)
    # Generated project-only notes (sase_artifacts, sase_beads, sase_sizes) and
    # the generated task_types web belong to the project layer, mirroring
    # memory init's include_project_memory split: the project root compiles
    # with them, the home root without.
    project_long_contents, project_long_error = (
        render_generated_project_long_memory_contents()
    )
    if project_long_error is not None:
        raise InstructionCompileError(project_long_error)
    project_long_notes = generated_long_notes(project_long_contents)

    def _collect_units(
        root: Path,
        title: str | None,
        entries: tuple[Any, ...],
        config_path: Path,
        *,
        include_project_memory: bool,
    ) -> MemoryRootUnits:
        try:
            read_root = memory_read_root(root)
        except Exception as exc:
            raise InstructionCompileError(
                f"cannot resolve the memory root for {str(root)!r}: {exc}"
            ) from exc
        # The web plan needs an explicit source dir; the audited read root is
        # what legacy memory init passes, and a missing tree compiles to no
        # webs rather than an error.
        source_root = (
            read_root
            if read_root is not None
            else root / CANONICAL_MEMORY_RELATIVE_ROOT
        )
        web_plan = memory_web_root_plan(
            root,
            source_memory_root=source_root,
            include_project_memory=include_project_memory,
        )
        if web_plan.blockers:
            raise InstructionCompileError("; ".join(web_plan.blockers))
        excluded = retired_note_relative_paths(
            root, include_project_memory=include_project_memory
        )
        try:
            linked_source = config_path.relative_to(root).as_posix()
        except ValueError:
            linked_source = config_path.as_posix()
        return collect_memory_root_units(
            root,
            title,
            project_name=facts.project,
            linked_entries=entries,
            linked_entries_source=Path(linked_source) if linked_source else None,
            generated_short_notes=short_notes,
            generated_long_notes=(project_long_notes if include_project_memory else {}),
            generated_web_notes=dict(web_plan.web_note_bodies or {}),
            source_memory_root=None,
            excluded_note_paths=excluded,
        )

    project_units = _collect_units(
        project_root,
        project_title,
        tuple(project_entries),
        project_config,
        include_project_memory=True,
    )
    if home_exists:
        home_units = _collect_units(
            home_root,
            home_title,
            tuple(home_entries),
            global_config,
            include_project_memory=False,
        )
    else:
        home_units = MemoryRootUnits(
            root=home_root,
            title=None,
            contract_inputs=ContractInputs(
                project_name=None, linked_entries=(), template_path=None
            ),
            core=(),
            references=(),
            webs=(),
            intros=project_units.intros,
        )

    return assemble_sections(
        facts,
        project_root=project_root,
        home_root=home_root,
        project_units=project_units,
        home_units=home_units,
        template_body=template_body,
        project_config=project_config,
        global_config=global_config,
        project_entries=tuple(project_entries),
        home_entries=tuple(home_entries),
    )


def compile_bundle(
    facts: InstructionFacts | Mapping[str, Any],
    *,
    project_root: Path | str,
    home_root: Path | str,
    use_cache: bool = True,
) -> CompiledBundle:
    """Compile the instruction bundle for *facts* without side effects here.

    Reads project and home memory through the structured units API, applies
    overlays, and writes the bundle bytes to the content-addressed store plus
    the section table to the render cache (unless ``use_cache`` is false, in
    which case the cache is bypassed but the store is still filled). Writes
    nothing under either root.
    """
    parsed = facts if isinstance(facts, InstructionFacts) else parse_facts(facts)
    project_path = Path(project_root)
    home_path = Path(home_root)
    started = time.perf_counter()
    home_base = cache.instructions_home()
    key_inputs = cache.collect_key_inputs(
        compiler_version=COMPILER_VERSION,
        actor=parsed.actor,
        mode=parsed.mode,
        provider=parsed.provider,
        project=parsed.project,
        project_root=project_path,
        home_root=home_path,
    )
    key = cache.compute_cache_key(key_inputs)
    if use_cache:
        entry = cache.read_cache_entry(home_base, key)
        if entry is not None:
            blob = cache.read_store_blob(home_base, str(entry["bundle_sha256"]))
            if blob is not None:
                render_ms = (time.perf_counter() - started) * 1000.0
                store_path = cache.bundle_store_path(
                    home_base, str(entry["bundle_sha256"])
                )
                return CompiledBundle(
                    text=blob,
                    sections=tuple(entry["sections"]),
                    sha256=str(entry["bundle_sha256"]),
                    total_bytes=int(entry["bundle_bytes"]),
                    total_lines=int(entry["bundle_lines"]),
                    tokens_est=int(entry["bundle_tokens_est"]),
                    layers={
                        layer: dict(totals)
                        for layer, totals in entry.get("layers", {}).items()
                    },
                    store_path=str(store_path),
                    render_ms=render_ms,
                    cache="hit",
                )
    bundle_text, builders = _compile_uncached(
        parsed, project_root=project_path, home_root=home_path
    )
    digest = hashlib.sha256(bundle_text.encode("utf-8")).hexdigest()
    store_path = cache.write_store_blob(home_base, digest, bundle_text)
    wire_sections: list[dict[str, Any]] = []
    offset = 0
    for builder in builders:
        if builder.text is None:
            wire_sections.append(section_wire_dict(builder, offset=None))
            continue
        wire_sections.append(section_wire_dict(builder, offset=offset))
        offset += len(builder.text.encode("utf-8"))
    total_bytes = len(bundle_text.encode("utf-8"))
    layers: dict[str, dict[str, int]] = {}
    for wire in wire_sections:
        totals = layers.setdefault(str(wire["layer"]), {"bytes": 0, "tokens_est": 0})
        if wire["status"] == "included":
            totals["bytes"] += int(wire["length"])
            totals["tokens_est"] += int(wire["tokens_est"])
    render_ms = (time.perf_counter() - started) * 1000.0
    cache_result = "miss" if use_cache else "bypass"
    if use_cache:
        cache.write_cache_entry(
            home_base,
            key,
            {
                "bundle_sha256": digest,
                "bundle_bytes": total_bytes,
                "bundle_lines": bundle_text.count("\n"),
                "bundle_tokens_est": sum(
                    int(wire["tokens_est"])
                    for wire in wire_sections
                    if wire["status"] == "included"
                ),
                "layers": layers,
                "sections": wire_sections,
            },
        )
    return CompiledBundle(
        text=bundle_text,
        sections=tuple(wire_sections),
        sha256=digest,
        total_bytes=total_bytes,
        total_lines=bundle_text.count("\n"),
        tokens_est=sum(
            int(wire["tokens_est"])
            for wire in wire_sections
            if wire["status"] == "included"
        ),
        layers=layers,
        store_path=str(store_path),
        render_ms=render_ms,
        cache=cache_result,
    )


__all__ = [
    "COMPILER_NAME",
    "COMPILER_VERSION",
    "CompiledBundle",
    "InstructionCompileError",
    "compile_bundle",
]
