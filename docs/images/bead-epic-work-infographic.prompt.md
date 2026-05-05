# Bead Epic Work Infographic Prompt

## Target

- Document: `docs/beads.md`
- Insertion point: after the opening paragraph and before `## Table of Contents`
- Image: `docs/images/bead-epic-work-infographic.png`
- Alt text: `Bead issue model, storage sync, and epic wave execution`

## Final GPT Image Prompt

Create a clean 16:9 landscape architecture infographic base for technical documentation about an issue tracker called
Bead. Light neutral background, crisp flat vector-like illustration, no logos, no decorative gradients, no fake
screenshots. IMPORTANT: use no readable words, no letters, no numbers, no symbols that look like text; leave intentional
blank label space inside panels for later deterministic labels.

Composition: two clearly separated main zones.

Left zone: issue data model. Show a hierarchy: one large container card at top with three small tier chips, several
child task cards below connected by thin lines, and dependency arrows showing one task ready and one task blocked.
Include simple status dots/checkmarks only, not text.

Center/bottom zone: storage and workspaces. Show a small database cylinder and a document/ledger stack connected with
bidirectional sync arrows. Show two workspace folders feeding into a merged read lens, and a separate primary-write
arrow into the database.

Right zone: epic execution flow. Show an epic command trigger feeding into three horizontal wave bands, each wave
containing small agent nodes connected by dependency arrows, with a final landing node at the far right waiting on every
phase agent node. Use clear arrow direction left-to-right.

Visual style: GitHub Markdown friendly, readable at 900px wide, restrained mixed accent colors (teal, blue, amber,
green, red accents) on a neutral white/off-white base, thin dark-gray strokes, generous spacing, professional
architecture diagram aesthetic. The final image should look complete even after adding short labels later.

## Post-Processing Notes

The generated base was intentionally text-free. Final labels were added deterministically with ImageMagick using DejaVu
Sans. Labels summarize the bead model, SQLite/JSONL Rust-backed storage, multi-workspace read/write behavior, Kahn-wave
phase scheduling, pre-claimed agents, and the final land agent.
