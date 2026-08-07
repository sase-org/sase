---
diagram: workflow-execution-infographic.png
embedding_doc: docs/workflow_spec.md
prompt_sidecar: docs/images/workflow-execution-infographic.prompt.md
critique_date: 2026-05-10
pdf: false
---

# Critique: `workflow-execution-infographic.png`

This critique reviews the infographic embedded immediately under the opening paragraph of
`docs/workflow_spec.md` (and above `## Table of Contents`). The image is a 1672×941 16:9 landscape
diagram with three vertical zones: a left column of two source blocks (`Inputs`, `Environment`); a
center execution lane of six rows labeled `agent`, `bash`, `python`, `hidden`, `parallel`, `HITL`,
surrounded top-and-bottom by thin bands labeled `if`, `for`, `while`, `repeat/until`; a floating
`prompt_part` document fragment that arrows into the agent row; and a right zone with a "Parallel
Branches" column (Branch A–D), a "Join (merge results)" panel listing `object`, `array`, `text`,
`lastOf`, and a single "Continue Workflow" exit arrow.

The original prompt is preserved in `workflow-execution-infographic.prompt.md`; deterministic
ImageMagick labels were composited on top of a no-text background to lock left-column terminology to
the spec. This critique is grounded in the current `docs/workflow_spec.md` and the shared
`docs/images/infographic-style-brief.md`.

## Summary

The diagram correctly captures the headline shape — inputs and environment flowing into an ordered
step lane with control wrappers, parallel fan-out, four join modes, and a HITL gate — and the
deterministic left-column relabel keeps the input/environment terminology aligned with the spec. The
biggest semantic problem is the **center lane treats `hidden` and `HITL` as peer execution types
alongside `agent`/`bash`/`python`/`parallel`**, which directly contradicts the prompt sidecar's own
guidance ("Make HITL read as a `hitl: true` human approval gate … not as a standalone execution
type") and the spec's modifier semantics for `hidden: true`. Several visual choices also imply
unsupported or misleading nesting, drop the `finally:` cleanup concept entirely, and label step
outputs with awkward composite strings (e.g. `output_agent_out`, `output_hidden_out`) instead of the
spec's `{{ step.field }}` model.

## Clarity issues a new user would hit

1. **`hidden` and `HITL` look like execution types.** A first-time reader sees a six-row vertical
   lane of equally weighted icons — `agent`, `bash`, `python`, `hidden`, `parallel`, `HITL` — and
   concludes there are six step types. The spec is explicit that `hidden: true` is a per-step
   modifier ("Any step can be marked `hidden: true`") and that `hitl: true` is a directive that can
   attach to `agent`, `bash`, or `python` steps. Treating them as their own rows in the same column
   as the four real execution types is the central clarity bug of the diagram.
2. **Control wrappers wrap the entire lane, suggesting global scope.** The `if` / `for` / `while` /
   `repeat-until` thin bands stretch from the top to the bottom of the central column, encompassing
   `agent`/`bash`/`python`/`hidden`/ `parallel`/`HITL` simultaneously. This visually implies that
   the four control wrappers apply to the whole workflow at once, when in reality each wrapper is a
   per-step field on a single step (`if:` and `for:` can combine; `while:` and `repeat:` are
   mutually exclusive on a step). A new reader cannot infer "I attach `for:` to one bash step", they
   read "I wrap the whole sequence in a `for` loop".
3. **`prompt_part` is shown injecting into the workflow's own agent row.** The arrow from the
   floating `prompt_part` document fragment terminates at the in-lane `agent` step. The spec's
   actual semantic is that `prompt_part` is expanded inline into the **calling/containing prompt**
   at the `#name(args)` reference site — not necessarily into any agent step within the same
   workflow. A new reader walks away thinking `prompt_part` is a way to prepend text to a downstream
   `agent` step in this workflow, missing the load-bearing case where a `.md` xprompt is
   _implicitly_ a single `prompt_part` step expanded at the user's call site.
4. **HITL pause does not name the user's actions.** The HITL row's annotation reads "Pause for
   review and approval" but the spec defines three distinct user actions on the gate — **Accept**,
   **Edit** (modify the output), and **Reject** (abort the workflow) — and a downstream
   `step.approved` field for `bash` / `python` HITL steps. Without these labels, a new reader cannot
   distinguish HITL from an unconditional pause.
5. **Output arrows are labeled with composite junk strings.** The arrows leaving each row carry the
   literal labels `output_agent_out`, `output`, `output`, `output_hidden_out`, plus an "artifacts
   (optional)" tag on bash/python. `output_agent_out` and `output_hidden_out` are not real terms in
   the spec; they read like a templating accident ("`output_<row>_out`") rather than deterministic
   post-processing. The spec's mental model is the named-output schema (`output: { field: type }`)
   referenced downstream as `{{ step_name.field }}`; none of that is depicted.
6. **The "Continue Workflow" exit arrow lives only on the parallel/join column.** The single
   rightmost arrow leaves from the join panel, with no equivalent on the linear lane, suggesting
   that "continuing the workflow" is a property of `parallel` rather than the default control flow.
   Parallel is just a step type; the workflow continues after every step.
7. **Inputs and Environment merge visually but are described separately in the spec.** The two left
   blocks are stacked with similar styling and a shared down-arrow into the lane. The spec keeps a
   sharper line: `input` is _typed user parameters validated at invocation_, while `environment` is
   _Jinja2-rendered key/value strings injected into `os.environ` for the whole session_. A reader
   might infer they are interchangeable channels into the same template context, which under-counts
   environment's process-env side effect.
8. **No depiction of cleanup / `finally: true`.** The spec dedicates a whole section to
   `finally: true` cleanup steps that run even after failures or HITL rejection. The infographic has
   no equivalent visual — no "always-runs" lane, no teardown badge, no rejection path off the HITL
   gate. A new reader cannot answer "what happens to my `rm -rf /tmp/x` step if the agent before it
   fails?" from this picture.
9. **Parallel-branch restrictions are invisible.** The right-side "Parallel Branches" depicts four
   arbitrary nested branches (A–D) without signaling that nested steps inside `parallel:` cannot use
   `for` / `repeat` / `while`, cannot nest another `parallel`, and cannot be `hitl: true`. Combined
   with point (2), the diagram suggests a reader can wrap the parallel block in a `for` loop _and_
   nest HITL inside parallel branches; the first is allowed, the second is not.
10. **Label hygiene at GitHub width.** At the embedded width, the four control-wrapper bands plus
    the right join panel plus the parallel column compete for horizontal space. The bottom
    `repeat/until` and `for` bands run very close to the HITL row's pause caption; the
    `Continue Workflow` arrow head overlaps the "lastOf" entry in the join panel. There is little
    slack on a narrow theme or smaller viewport.

## Accuracy errors against current spec

These are checked against `docs/workflow_spec.md` (the embedding doc) and the shared
`infographic-style-brief.md`.

1. **`hidden` is a modifier, not an execution type.** `workflow_spec.md` §"Hidden Steps" says: "Any
   step can be marked `hidden: true` to suppress it from the ACE TUI Agents tab. Hidden steps
   execute normally but don't appear as visible agents." The brief enumerates `hidden` in its
   step-type list, but the brief is itself imprecise here; the spec is authoritative. Showing
   `hidden` as a distinct row with its own output arrow is wrong against the spec's semantics.
2. **HITL is a directive (`hitl: true`), not an execution type.** The spec puts HITL under
   "Human-in-the-Loop" as a directive that pauses execution after an `agent`, `bash`, or `python`
   step. The prompt sidecar explicitly instructed "not as a standalone execution type"; the rendered
   image violates its own brief by giving HITL a peer row in the execution lane.
3. **Five real execution types, not six rows.** The spec lists exactly five execution types as
   mutually exclusive on a single step: `agent`, `prompt_part`, `bash`, `python`, `parallel`. The
   image's central column shows four of those (`agent`, `bash`, `python`, `parallel`) plus two
   non-types (`hidden`, `HITL`). `prompt_part` is the fifth real type and is depicted only as a
   floating fragment, not as a peer in the execution lane.
4. **`prompt_part` injection target is wrong.** The spec: "When a workflow is referenced via
   `#name(args)`, the `prompt_part` content is expanded inline into the calling prompt." The arrow
   in the image goes from `prompt_part` into the _workflow's own_ `agent` row, which mis-locates the
   injection. The standalone case (a `.md` xprompt is internally a single `prompt_part` step
   expanded into the user's prompt) is not depictable from the current arrow.
5. **`artifact: stdout` is conflated with `output`.** The spec separates two output channels:
   structured `output: { field: type }` (parsed via JSON / `key=value` / text fallback) and
   `artifact: stdout` (captures stdout to `{artifacts_dir}/{step_name}.stdout` and exposes
   `{{ step_name._artifact }}`). The image's "artifacts (optional)" tag on bash/python is the only
   nod, and it sits next to `output` without distinguishing the file-path vs. structured-fields
   semantic. The `_artifact` reference path is not surfaced anywhere.
6. **Cross-step references via named outputs are not visualised.** The spec's data-flow model is
   `{{ step_name.field }}` lookups against an output schema, validated at load time (§"Cross-Step
   Field Type Checking"). The image shows anonymous output arrows leaving each row with no
   named-field references between rows, so a reader cannot derive how step B reads step A's data.
7. **`finally: true` cleanup is missing entirely.** The spec dedicates a section to `finally: true`
   semantics (still runs after failure or HITL-reject; must be placed after all non-finally steps;
   can combine with `if:`). No element of the diagram represents this. The brief is silent on
   `finally:`, but it is a documented top-level concept on par with control flow and HITL.
8. **`use:` step imports are not visualised.** The spec §"Step Imports" defines a `use: shared/foo`
   syntax that pulls a step definition from `steps/` directories with override semantics. This is a
   real, top-level reuse mechanism in the workflow format. The image shows no symbol for it.
   Acceptable simplification only if the omission is consistent — right now it sits next to
   `prompt_part` (which IS shown), creating an asymmetry.
9. **`on_error: stop` / `continue` for `for:` loops is missing.** The spec §"For-Loop Error
   Handling" calls out per-step-type defaults (`agent` → continue, `bash`/`python` → stop) and an
   explicit override. The diagram's `for` wrapper has no failure-path branch to represent this;
   readers using `for:` over agent steps in production will wonder where the "skip-and-continue"
   semantic comes from.
10. **Join modes are correctly listed but un-anchored to context.** The four labels (`object`,
    `array`, `text`, `lastOf`) match the spec's table. But the spec also encodes which mode is the
    _default_ for which producer (`object` → default for `parallel:`, `array` → default for `for:`);
    the diagram lists them as a flat menu, missing the default-binding that determines what users
    get when they omit `join:`.
11. **Parallel join is shown as the workflow's terminus.** The "Continue Workflow" arrow leaves the
    join panel as if the workflow ends there. In the spec, `parallel` is just one step type — its
    result feeds downstream steps via `{{ parallel_step.nested.field }}` exactly like any other
    step. The terminal arrow placement misframes the role of the parallel block.
12. **No depiction of `hitl` post-state (`step.approved`).** The spec: "After an accepted `bash` or
    `python` HITL step, `step.approved` is set to `true` for downstream conditions". This is a
    load-bearing pattern for "ask for permission then act" workflows, and the diagram has no symbol
    for the `approved` field flowing forward.
13. **Prompt sidecar QA note (Phase 7) and current image disagree on HITL framing.** The sidecar's
    post-processing section claims the HITL framing was audited as a `hitl: true` human approval
    gate "not as a standalone execution type", but the rendered image shows HITL as a row in the
    execution lane. Either the audit pre-dated the most recent regen, or the audit accepted the
    row-style depiction; in either case the documented intent and the rendered visual are out of
    sync.

## Concrete suggested changes for the regenerated image

These are change requests the regen agent should pass into its GPT image prompt and/or its
post-processing label script, scoped to the diagram only.

1. **Cut the central lane from six rows to five execution types** in this order: `agent`,
   `prompt_part`, `bash`, `python`, `parallel`. `prompt_part` becomes a peer row (still styled as a
   "text fragment" icon, not an LLM/process icon) so all five mutually-exclusive types are visible
   together.
2. **Render `hidden` as a small badge** ("hidden: true — suppressed from ACE TUI") attached to one
   example row (e.g. the `python` row), demonstrating that any step can carry the modifier rather
   than depicting it as its own row.
3. **Render `HITL` as an approval gate symbol** straddling the boundary between a step row and its
   downstream arrow — ideally a small "pause" diamond hooked onto the `agent`, `bash`, and `python`
   rows (one symbol, three dotted anchors) with the user-action labels **Accept / Edit / Reject**
   spelled out, plus an `approved → downstream` ribbon for the `bash`/`python` post-state.
4. **Move the four control wrappers (`if`, `for`, `while`, `repeat/until`) from full-lane bands to
   per-step brackets.** Show one example bracket on a single representative step (e.g. `if:` on
   `agent`, `for:` on `bash`, `while:`/`repeat:` on `python`) so readers see "modifier on one step"
   instead of "wrapper around the whole workflow". Note in a small caption that `while:` and
   `repeat:` are mutually exclusive on a step.
5. **Re-target the `prompt_part` arrow.** Instead of arrowing into the workflow's own `agent` row,
   draw it leaving the workflow boundary toward an external "calling prompt" tile labeled
   `#workflow_name(args)`. Add a small caption: "expanded inline into the calling prompt at the
   `#name` reference site".
6. **Replace `output_agent_out` / `output_hidden_out` arrow labels** with the spec's named-output
   model: each step's exit arrow should carry `output: { field: type }` and a small
   `{{ step.field }}` example flowing into the next step. Introduce a separate
   `artifact: stdout → {{ step._artifact }}` arrow on `bash`/`python` to distinguish structured
   outputs from file-captured stdout.
7. **Add a `finally:` lane** as a horizontal strip below the main lane with one or two example
   "always-runs" cleanup steps and a dotted "runs even after failure or HITL-reject" connector from
   the failure paths.
8. **Add a small `use:` import badge** on one example step (or drop `prompt_part`'s peer treatment
   for symmetry — either both `prompt_part`-as-step-type and `use:`-as-import are shown, or both are
   omitted; the current asymmetry is the bug).
9. **Drop the terminal "Continue Workflow" arrow from the join panel** and instead route the joined
   parallel result into a downstream "next step" tile that consumes
   `{{ parallel_step.branch.field }}`, mirroring how every other step feeds forward.
10. **Annotate join modes with their default bindings.** Next to each of the four modes show the
    producer they default to: `object` → default for `parallel:`, `array` → default for `for:`,
    `text` and `lastOf` → opt-in. This is the information that determines user behavior when `join:`
    is omitted.
11. **Surface the parallel-nesting restrictions** as a small caption inside the "Parallel Branches"
    column: "nested steps cannot use `for` / `while` / `repeat`, cannot nest `parallel`, and cannot
    be `hitl: true`". This forecloses the most common misreads.
12. **Clarify Inputs vs Environment** with a one-line caption per block: `Inputs` → "typed
    user-supplied parameters, validated at invocation"; `Environment` → "Jinja2-rendered key/value
    strings, injected into `os.environ` for the session". Keep them visually adjacent but clearly
    distinct, not stacked-as-one source.
13. **Update the prompt sidecar's Phase-7 QA note** if the HITL row stays as a row in any future
    regen — currently the sidecar's claim ("not as a standalone execution type") and the rendered
    image disagree. The audit log should match the rendered artifact.

## Out of scope for this critique

- The PNG, the prompt sidecar, and `docs/workflow_spec.md` itself are unchanged by this phase per
  the epic plan in `sdd/epics/202605/diagram_review.md`. Phase 19 (`sase-2s.19`, "Regenerate
  diagram: workflow-execution") owns the regenerated image, the updated prompt sidecar if needed,
  and any related label-composition tooling.
- Style consistency across all infographics in the diagram-review epic is the regen phase's concern;
  this critique only addresses what the workflow-execution diagram alone gets right and wrong
  against its embedding doc and shared style brief.
