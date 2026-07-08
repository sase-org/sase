---
pdf: false
---

# Memory Directory Map Prompt

## Target

Packaged source asset: `src/sase/memory/assets/memory-directory-map.png`.

Copied generated asset: `memory/assets/memory-directory-map.png`.

Embedded in the generated `memory/README.md` immediately after the opening introductory paragraph.

## Intended Alt Text

Memory architecture showing short notes always in context, long notes read on demand, generated provider shims, and
drift checks.

## Placeholder Status

The current PNG is a valid placeholder only. Phase 3 replaces both PNG copies with the final infographic and keeps them
byte-identical. This sidecar records the full brief needed to regenerate the final image without chat history.

## Final GPT Image Prompt

Use case: architecture infographic. Asset type: documentation PNG for the SASE memory README.

Primary request: Create a text-free 16:9 landscape structural base for an architecture infographic explaining how SASE
memory markdown files become agent context and generated documentation. The final image should look like a crisp
software documentation diagram, not marketing art.

Style and medium: light neutral background, strong contrast, flat vector-like panels, thin outlines, clear arrows,
swimlanes, and a restrained multi-accent palette. Use distinct accents for concepts such as source notes, always-loaded
short notes, on-demand long notes, generated files, and freshness checks. Avoid single-hue themes, dark mode, decorative
gradients, logos, fake terminal screenshots, dense paragraphs, watermarks, and model-generated text.

Composition: left-to-right story with a bottom freshness loop band.

Left zone: show a stack of markdown note cards representing `memory/*.md`. Each card has a small blank frontmatter-tag
area suitable for deterministic labels.

Middle zone: split the flow into two clear horizontal lanes. The upper lane is for Tier 1 short notes flowing into
`AGENTS.md` and then fanning out to provider shims. The lower lane is for Tier 2 long notes flowing to an audited
`sase memory read` step before entering an agent context. The two lanes should be visually distinct but part of the same
system.

Right zone: show the agent working context and the generated self-updating `memory/README.md`. The working context
should visually contain always-loaded short-note context and optionally fetched long-note reference context.

Bottom band: show a freshness loop where `sase memory init` regenerates the README, `AGENTS.md`, and provider shims, and
`sase validate` checks for drift. Use a simple loop or gate motif.

Framing: about 1600x900, landscape, generous blank label zones, readable at GitHub Markdown width.

Constraints: Do not include any generated text in the raster base. Do not include logos. Do not imply that image
generation runs during `sase memory init`. Do not show provider shims diverging from `AGENTS.md`; they are
byte-identical generated outputs.

## Deterministic Labels To Add

Add labels locally with SVG/ImageMagick or an equivalent deterministic post-processing step using a recorded font and
exact coordinates. Keep labels short and dark on light backgrounds.

Required labels:

- `memory/*.md`
- `frontmatter`
- `type: short | long`
- `parent:`
- `description:`
- `keywords:`
- `Tier 1: short notes`
- `always in context`
- `AGENTS.md`
- `provider shims`
- `CLAUDE.md`
- `GEMINI.md`
- `QWEN.md`
- `OPENCODE.md`
- `Tier 2: long notes`
- `reference, loaded when relevant`
- `sase memory read`
- `audited`
- `agent context`
- `memory/README.md`
- `sase memory init`
- `regenerate`
- `sase validate`
- `drift gate`

## Post-Processing Notes

The final PNG should be produced by generating a text-free base, then adding the deterministic labels above. Record the
final font, label coordinates, commands, and any image cleanup steps here when the placeholder is replaced.

The placeholder PNG was generated locally as a neutral 1600x900 diagram marker. It is intentionally not the final
infographic.
