---
pdf: false
---

# XPrompt Resolution Infographic Prompt

## Target

- Document: `docs/xprompt.md`
- Insertion point: after the introductory "Use xprompts when you want to" list and before `## Table of Contents`.
- Final asset: `docs/images/xprompt-resolution-infographic.png`

## Intended Alt Text

Diagram showing user prompt references flowing through xprompt resolution stages into inline prompt text, standalone
workflows, workflow graphs, or multi-agent fan-out.

## Final GPT Image Prompt

This prompt intentionally asks the image model for a no-text structural base. The committed PNG includes deterministic
labels added afterward, as recorded in the post-processing notes.

Use case: infographic-diagram

Asset type: documentation infographic for GitHub Markdown, final PNG will be post-processed with deterministic labels.

Primary request: Create a clean landscape 16:9 architecture infographic base illustrating SASE xprompt resolution from
prompt inputs through a resolver pipeline to output/runtime outcomes. Use a light neutral background, crisp flat
vector-like panels, thin outlines, arrows, swimlanes, and simple abstract icons only. Leave generous blank whitespace
inside every box for labels that will be added later. Include no readable text, no pseudo-text, no logos, no terminal
screenshots, no code snippets, and no watermarks.

Composition: 1672x941-ish 16:9. Three main zones left to right. Left zone: a prompt-input panel with five blank card
rows and one separate protected-content callout card below it. Include a visible arrow from the protected-content
callout toward the resolver pipeline. Middle zone: large resolver panel with a top pre-stage area for workspace
dispatch, then a vertical processing pipeline. Show a loop/iteration visual around the central
parse/lookup/validate/render cluster, plus a sidebar stack for discovery priority with many small blank rungs. Add
arrows between stages, including an early alias/masking sequence and a later post-expansion/directives/memory sequence.
Right zone: outputs panel with four blank output cards; visually distinguish the workflow graph/explain card as a
developer tool rather than a runtime output. Use a restrained multi-accent palette with teal, blue, amber, green,
purple, and slate accents. Professional technical docs architecture diagram style, readable at documentation width, no
dark theme, and no gradients that reduce label contrast.

## Post-Processing Notes

- The GPT-generated image was used as a low-opacity structural base with no model-generated text.
- Deterministic SVG labels and diagram panels were rendered to PNG with ImageMagick using DejaVu Sans fonts so technical
  terminology stays exact and readable.
- The revised labels follow the documented resolver order: workspace dispatch, alias substitution, protected-content
  masking, iterative reference expansion, discovery lookup, argument parsing with `$(cmd)`, typed-input validation,
  Jinja2/legacy rendering, unmasking, directive extraction, dynamic-memory append, and final expanded prompt text.
- The discovery sidebar records the documented priority stack, including project-local paths, user paths, config,
  `memory/long/*.md`, `sase.yml`, plugins, and the two package-provided xprompt locations.
- Runtime outputs are separated from the developer-tool output: inline expansion, standalone workflow launch,
  multi-agent fan-out, and `sase xprompt graph`/`explain`.

## Audit Notes

- Verified on 2026-05-10 that `docs/xprompt.md` embeds `docs/images/xprompt-resolution-infographic.png` at the target
  insertion point with the intended alt text.
- Verified the committed image is a 1672x941 PNG and that its labels address the prior critique: aliases run first,
  masking precedes expansion, expansion is iterative, directives are extracted after expansion, dynamic memory is a
  resolver-driven append, and multi-agent fan-out is depth-capped rather than one-level-only.
- Checked the depicted behaviors against `docs/xprompt.md`, `docs/images/xprompt-resolution-infographic.critique.md`,
  and nearby xprompt/multi-agent/dynamic-memory implementation references.
