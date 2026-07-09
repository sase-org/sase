---
pdf: false
---

# Bead Epic Work Infographic Prompt

## Target

- Document: `docs/beads.md`
- Insertion point: after the opening paragraph and before `## Table of Contents`
- Image: `docs/images/bead-epic-work-infographic.png`
- Alt text: `Bead issue model, storage sync, and epic wave execution`

## Final GPT Image Prompt

- Use case: infographic-diagram
- Asset type: documentation infographic base for `docs/images/bead-epic-work-infographic.png`

Primary request: Create a clean 16:9 landscape architecture infographic base for technical documentation about an issue
tracker called Bead and its epic work automation. This is a text-free base image: use no readable words, no letters, no
numbers, and no symbols that look like text. Leave generous blank label spaces for deterministic labels added later.

Style/medium: crisp flat vector-like technical architecture diagram, GitHub Markdown friendly, light neutral background,
thin dark-gray strokes, restrained accent colors, no logos, no decorative gradients, no fake screenshots.

Composition/framing: three clearly separated zones with visible gutters and faint section tints.

Left zone, issue model: show a large plan bead container at the top with three small tier chips. Emphasize the middle
chip as the epic tier, and show a thin arrow from that chip toward the epic execution zone. Under the plan bead, show
three child phase cards connected by hierarchy lines and dependency arrows. Include three small status pips on or near
the phase cards: open, in-progress, and closed/check style. Show one phase as ready, one in progress, and one blocked
via neutral iconography only, with no text.

Bottom-left zone, storage and workspaces: show three workspace folder icons feeding into a merged-read lens. Show a
separate primary-write arrow from the primary workspace path into a SQLite-style database cylinder. Show a Rust core
glyph or block sending mutation arrows into the database. Show a distinct document stack for JSONL export beside the
database, with a one-way export arrow from database to document stack and a one-way rebuild/import arrow from document
stack back to database. Keep the database and JSONL document visually distinct.

Right zone, epic execution: show a command trigger shape feeding first into a staged pre-launch ribbon with three
numbered-looking but textless chips, then into three horizontal Kahn-wave bands. Each wave band contains small circular
phase-agent nodes; dependency arrows connect nodes left-to-right and between waves. Add a global header strip above all
waves for cross-wave properties. Show a final landing node at the far right. Draw incoming wait arrows from
representative nodes in all three waves into the landing node, not only from the last wave.

Color palette: neutral white/off-white base; teal for plan/model, blue for storage/read, green for primary write/Rust
mutation, amber for epic accents, red for blocked state, dark gray for connectors.

Constraints: 16:9 landscape, readable at 900px wide after labels are added, complete-looking after post-processing,
consistent with polished software documentation diagrams. Avoid tiny details, dense texture, ornamental backgrounds,
drop shadows that obscure labels, and any generated text.

## Post-Processing Notes

The generated base was intentionally text-free and was saved by the built-in image generation tool under
`$CODEX_HOME/generated_images/.../ig_07a7d36da75a7b5d016a00ca10ce8c81968ab0bd34e7f41936.png`.

Final labels were added locally with ImageMagick and DejaVu Sans. The deterministic labels address the critique by
showing:

- all three phase states, including the pre-claimed `in_progress` state;
- tier semantics, with `epic` feeding `sase bead work` and `plan` representing non-executable planning records;
- three workspace folders feeding merged reads, with primary writes labeled on the write path;
- Rust-backed mutations, `beads.db` as the gitignored cache, and `issues.jsonl` as the git-tracked export/rebuild
  artifact;
- the command's pre-launch sequence: ready flag, pre-claim, dispatch;
- a global wave caption for shared behavior instead of per-wave misleading captions;
- land-agent wait arrows from all waves, matching `land_waits_on` for every launched phase agent.
