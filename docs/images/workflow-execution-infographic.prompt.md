---
pdf: false
---

# Workflow Execution Infographic Prompt

## Target

Embedded in `docs/workflow_spec.md` after the opening paragraph and before
`## Table of Contents`.

## Intended Alt Text

Workflow execution model showing inputs, environment, five execution step types, prompt
injection, per-step control modifiers, named outputs, artifacts, parallel branch joins,
HITL gates, and finally cleanup.

## Final GPT Image Prompt

Use case: infographic-diagram Asset type: documentation PNG for
`docs/images/workflow-execution-infographic.png` in a technical Markdown manual.

Primary request: Create a revised 16:9 landscape architecture infographic for the SASE
YAML workflow execution model, addressing these correctness requirements: five real step
execution types are `agent`, `prompt_part`, `bash`, `python`, and `parallel`; `hidden`
is a modifier badge, not a step type; HITL is a `hitl: true` approval gate attached
after `agent` / `bash` / `python` steps, not a step type; `prompt_part` expands into a
calling prompt at the `#name(args)` reference site; named outputs and `artifact: stdout`
flow forward; parallel branches join and then feed a downstream next step; `finally:`
cleanup runs even after failure or HITL rejection.

Style/medium: crisp software documentation architecture diagram, light neutral
background, clean vector-like blocks, restrained but distinct accent colors, readable at
GitHub Markdown width, no logos, no screenshots.

Composition/framing: 16:9, generous spacing, three zones. Left zone has two distinct
source blocks titled `Inputs` and `Environment`. Center zone has an ordered workflow
lane with five horizontal step cards in order: `agent`, `prompt_part`, `bash`, `python`,
`parallel`. Put small per-step control brackets near example cards labeled `if:`,
`for:`, `while:`, `repeat/until`; make the bracket scope visibly per-step. Attach a
small `hidden: true` badge to one example card. Add a reusable `use:` import badge on
one step. Place a HITL approval gate diamond on the downstream side of the `agent` /
`bash` / `python` area with short labels `Accept`, `Edit`, `Reject` and an
`approved -> downstream` hint. Right zone shows parallel fan-out into branches A, B, C,
then a join panel with four modes and default notes, then a downstream next step tile
consuming a named field. Bottom strip shows `finally:` cleanup steps with a dotted
connector from failure/reject paths and the note `always runs`.

Text constraints: use only short labels from the workflow spec, including `Inputs`,
`typed params`, `validated at invocation`, `Environment`, `Jinja2 env vars`,
`os.environ session`, `output: { field: type }`, `{{ step.field }}`, `artifact: stdout`,
`{{ step._artifact }}`, `#name(args)`, `calling prompt`, `expanded inline`,
`hitl: true`, `Accept`, `Edit`, `Reject`, `approved`, `object default for parallel`,
`array default for for`, `text opt-in`, `lastOf opt-in`,
`{{ parallel_step.branch.field }}`, `finally:`, `cleanup`, `always runs`,
`after failure or reject`, and `no nested for/while/repeat, parallel, or HITL`.

Constraints: Do not show `hidden` or HITL as rows in the execution-type lane. Do not
draw control wrappers around the whole workflow lane; show per-step brackets only. Do
not make the parallel join the terminus; it must feed a next step. Keep labels large and
legible, dark text on light blocks. Avoid dense paragraphs and avoid decorative
gradients. No watermarks.

## Post-Processing Notes

Generated with the built-in image generation tool on 2026-05-10, copied into
`docs/images/workflow-execution-infographic.png`, then lightly post-processed with
ImageMagick to correct generated text defects in the title and environment block while
preserving the generated composition.

The regenerated image addresses the critique in
`docs/images/workflow-execution-infographic.critique.md`: `hidden` is a badge, HITL
appears as approval gates rather than a step row, control wrappers are scoped to example
steps, `prompt_part` is shown expanding into a calling prompt, parallel join feeds a
downstream next step, and a `finally:` cleanup strip is present.
