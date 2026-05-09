---
pdf: false
---

# Workflow Execution Infographic Prompt

## Target

Embedded in `docs/workflow_spec.md` after the opening paragraph and before `## Table of Contents`.

## Intended Alt Text

Workflow execution model showing inputs, environment, ordered steps, prompt injection, control flow wrappers, artifacts,
parallel branches, join modes, and human-in-the-loop gates.

## Final GPT Image Prompt

Create a 16:9 landscape documentation infographic for a technical Markdown manual, light neutral background, crisp
architecture diagram style, clean blocks and arrows, restrained but distinct accent colors.

Subject: SASE YAML workflow execution model.

Composition:

- Left column: "Inputs" and "Environment" as two source blocks flowing into a central execution lane.
- Center lane: ordered workflow steps moving left to right / top to bottom. Include short labels for the execution forms
  and workflow controls readers see in `docs/workflow_spec.md`: agent, bash, python, hidden, parallel, and HITL.
- Make prompt_part visually distinct as text injection into an agent prompt, not a separate LLM/model call. Show it as a
  small document fragment feeding into the agent prompt path.
- Show bash/python producing stdout and optional artifacts; show named outputs/artifacts flowing forward between steps.
- Around the center lane, show control wrappers as thin bands or brackets labeled: if, for, while, repeat/until.
- Right side: parallel branches split, execute concurrently, and join back together. Include four compact join labels:
  object, array, text, lastOf.
- Make HITL read as a `hitl: true` human approval gate that can pause after agent, bash, or python work, not as a
  standalone execution type.

Style requirements:

- Technical architecture infographic, not marketing art.
- No logos, no screenshots, no code paragraphs, no dense body text.
- Use short legible labels only; dark text on light blocks; generous spacing.
- Avoid decorative gradients and avoid a one-hue palette.
- Use simple line icons and arrows; readable at GitHub Markdown width.
- Final image should feel consistent with a software documentation diagram.

## Post-Processing Notes

Generated with the built-in image generation tool, copied into `docs/images/workflow-execution-infographic.png`, then
post-processed with ImageMagick to replace generated left-column labels with deterministic workflow-spec terminology:
input parameters, defaults and types, invocation arguments, template context, environment variables, Jinja2 rendering,
shared step environment, and values available to steps.

Audited on 2026-05-09 against `docs/workflow_spec.md`, `docs/images/infographic-style-brief.md`, and the current
`docs/images/workflow-execution-infographic.png` (1672x941). The target insertion point, Markdown alt text, left-column
labels, prompt_part injection depiction, join labels, and HITL approval-gate framing match the current documentation.
