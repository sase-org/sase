# XPrompt Resolution Infographic Prompt

## Target

- Document: `docs/xprompt.md`
- Insertion point: after the introductory "Use xprompts when you want to" list and before `## Table of Contents`.
- Final asset: `docs/images/xprompt-resolution-infographic.png`

## Intended Alt Text

Diagram showing user prompt references flowing through xprompt resolution stages into inline prompt text, standalone
workflows, workflow graphs, or multi-agent fan-out.

## Final GPT Image Prompt

Use case: infographic-diagram

Asset type: documentation infographic for GitHub Markdown, final PNG will be post-processed with deterministic labels.

Primary request: Create a clean landscape 16:9 architecture infographic illustrating how SASE xprompt references become
final prompts or launched workflows. Use a light neutral background, crisp flat vector-like panels, arrows, swimlanes,
and simple abstract icons. Leave ample whitespace inside every box for labels that will be added later. Include no
readable text, no pseudo-text, no logos, no terminal screenshots, no code snippets, no watermarks.

Composition: left-to-right flow with three main zones. Left zone: a user prompt card containing small abstract tokens
representing `#name`, `#!workflow`, directives, workspace refs, and dynamic memory triggers. Middle zone: a processing
pipeline with stacked steps and arrows, including one mini stack for discovery priority. Right zone: four output cards
showing inline prompt fragment, standalone workflow execution, workflow graph, and multi-agent fan-out. Include a subtle
side branch for protected/disabled-region masking before parsing. Visual style should match a professional technical
docs architecture diagram, approximately 1672x941 or 16:9, light background, restrained multi-accent palette with teal,
blue, amber, green, and slate accents. Ensure all boxes are blank enough for overlaid labels and all arrows are visually
unambiguous.

## Post-Processing Notes

- The generated image was used as a clean structural base with no model-generated text.
- Deterministic labels were added locally with ImageMagick using DejaVu Sans fonts so the terminology matches
  `docs/xprompt.md`.
- Labels intentionally stay short and cover the documented flow: reference inputs, protected/disabled-region masking,
  parsing, aliases, discovery priority, typed input validation, Jinja2/directive rendering, dynamic memory, standalone
  workflow launch, workflow graph inspection, and one-level multi-agent fan-out.
- Phase 7 QA polished the final overlay to remove clipped section/output labels while preserving the original diagram
  structure.
