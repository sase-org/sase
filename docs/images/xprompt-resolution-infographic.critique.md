---
diagram: docs/images/xprompt-resolution-infographic.png
embedded_in: none
phase: critique
pdf: false
---

# Critique: `xprompt-resolution-infographic.png`

## Summary

This infographic was formerly embedded in `docs/xprompt.md`. It gets the high-level shape right — three swimlanes
(inputs → resolution pipeline → outputs), with a side "Discovery stack" annotation off the resolution column. The four
output cards on the right are all real artifacts of the pipeline and read clearly. The input column gathers the right
surface-level concepts (`#name`, `#!workflow`, `%directives`, workspace refs) and the bottom-left "Fences + disabled
regions" callout names the right two protective constructs.

The substantive problems are in the **middle column**: the pipeline stages are listed in the wrong order, the
"directives" stage is fused into Jinja2 rendering even though directives are extracted in a separate, later step, and
two real stages of the resolver — alias substitution (which actually runs _first_) and recursive iterative expansion —
are misplaced or absent. The "Discovery stack" itself collapses the priority slots into five and labels them in a way
that does not match the documented discovery order. The stale "keyword trigger" entry on the input column also depicts a
removed legacy feature. These are accuracy issues a reader checking the diagram against `docs/xprompt.md` and
`src/sase/xprompt/processor.py` will notice immediately.

## What's actually in the rendered PNG

Reading the committed `xprompt-resolution-infographic.png` directly:

- Three top-of-frame section labels: **INPUTS** | **RESOLUTION** | **OUTPUTS**.
- Left column ("INPUTS"), top-to-bottom card list:
  - `#name / #name(args)` — "inline prompt fragments"
  - `#!workflow` — "launch standalone YAML workflow"
  - `%directives` — "append, override, repeat"
  - `#cd / #gh refs` — "workspace selection first"
  - keyword trigger — obsolete legacy row
  - A separate boxed callout at the bottom: **Fences + disabled regions**.
- Middle column ("RESOLUTION"), pipeline of stacked stages with downward arrows, top to bottom:
  1. **Mask protected regions** — "fences and disabled regions stay literal"
  2. **Parse references** — "find references after safe mask"
  3. **Apply aliases** — "shorthand + namespaced refs"
  4. **Discovery order** — "find matching source xms" (with a side-branch arrow into a stacked **Discovery stack**:
     `project-local`, `user/project`, `config`, `plugins`, `6 built-in`)
  5. **Validate typed inputs** — "coerce declared prompt inputs"
  6. **Render Jinja2 + directives** — "final prompt body or workflow launch"
- Right column ("OUTPUTS"), four output cards:
  - **Inline prompt_part** — "#name expands to text"
  - **Standalone workflow** — "#!name runs a workflow"
  - **Workflow graph** — "explain and graph steps"
  - **Multi-agent fan-out** — "one-level split into agents"

## Clarity issues a new user would hit

1. **The input column blurs different concepts.** It mixes reference syntax (`#name`, `#!workflow`, workspace refs),
   directives (`%directives`), and a stale keyword-trigger row into one bulleted stack. A reader new to xprompts cannot
   tell which of these are something the user types and which are obsolete. At minimum the column should split into
   "What the user writes in a prompt" and "Resolver support mechanics", and the keyword-trigger row should be removed.
2. **The "Fences + disabled regions" callout dangles.** It sits below the inputs as a separate floating box with no
   arrow into the pipeline. A new user has to guess that this content travels with the prompt and is then _protected_
   inside the resolver. An explicit arrow from this callout into the **Mask protected regions** stage (the very thing
   that protects them) would close the loop.
3. **`%directives` chip says "append, override, repeat" — those are not the salient categories.** The actual functional
   categories of directives are launch overrides (`%model`, `%name`, `%group`, `%hide`, `%auto`), scheduling (`%wait`,
   `%wait(time=...)`, `#t`), and fan-out (`%alt`/`%(`, `%repeat`, `%{...}`). "Append, override, repeat" picks three
   behaviors that don't map cleanly to the directive surface in `docs/xprompt.md` and isn't a useful taxonomy for a new
   reader.
4. **`#cd / #gh refs` says "workspace selection first" but the pipeline doesn't show that.** The caption hints that
   workspace refs are special and run before everything else, but the resolution column has no chip representing "pick
   workspace, then run the rest of the prompt." A new user can't see _where in the pipeline_ the workspace selection
   actually happens — which is a fair question because, as `docs/xprompt.md` notes, "they control where the agent runs
   before the rest of the prompt is executed."
5. **"Discovery order" / "Discovery stack" are not the same thing.** "Discovery order" is a property of name resolution
   (which catalog source wins on collisions). The diagram draws it as a phase of the pipeline plus a side stack, which
   makes it look like a separate runtime stage. In reality, discovery is just _the lookup table consulted by_ the parse
   stage when it resolves a name. Visually merging it with "Parse references" (with the priority list as a sidebar)
   would more honestly reflect the code.
6. **`Inline prompt_part` is internal jargon.** `prompt_part` is the name of the underlying single-step workflow type;
   it is not surfaced in the user-facing reference syntax table. Users see `#name` and an inline expansion result. A
   plain label like **Inline expansion** or **Inline prompt fragment** matches the doc terminology ("inline-capable
   xprompt").
7. **"Workflow graph" output card sits on the same plane as runtime outputs.** Inline expansion, standalone workflow
   launch, and multi-agent fan-out are _runtime_ outcomes of resolving a reference. Workflow graph is a developer tool
   produced by `sase xprompt graph` (and the analogous `sase xprompt explain`). Putting it as a fourth peer output
   suggests it happens automatically, when really it requires the user to invoke a CLI subcommand. It belongs in a
   visually distinct "developer tools" lane or annotated as "(via `sase xprompt graph`/`explain`)" so a new reader does
   not assume the resolver always emits a graph.
8. **No visual cue that expansion is iterative.** The middle column reads as a one-shot pipeline. Recursive expansion
   (xprompts whose bodies reference other xprompts, looped up to 100 iterations — see `_MAX_EXPANSION_ITERATIONS` in
   `processor.py`) is one of the most surprising behaviors for new users and is invisible here. A loop-back arrow on the
   parse → render section, captioned "iterate until no refs remain (≤100 passes)", would land it.

## Accuracy issues vs. code and doc

Grounding against `src/sase/xprompt/processor.py` (`process_xprompt_references` lines 258–281,
`process_xprompt_references_with_catalog` lines 284–330, the iteration loop at lines 327–334),
`src/sase/llm_provider/preprocessing.py` (lines 80–101 — order of expansion vs. directive extraction), and
`docs/xprompt.md` (Discovery Order table, XPrompt Aliases section, Recursive Expansion section, Directives section):

1. **Pipeline stage order is wrong.** Actual execution order from the code is:
   1. **Resolve xprompt aliases** (`resolve_xprompt_aliases`, processor.py line 264) — text-level substitution that runs
      _before_ anything else. The doc explicitly states: "XPrompt aliases provide raw text-level substitution that runs
      _before_ any other xprompt processing."
   2. **Mask fenced code blocks** (`protect_fenced_blocks`, processor.py line 321).
   3. **Mask disabled regions** (`protect_disabled_regions`, line 325).
   4. **Iteration loop** (lines 327–334), each pass: a. Preprocess shorthand syntax. b. Find references via
      `_XPROMPT_PATTERN`. c. Look up name in the merged xprompt catalog (this is where the discovery-order priority is
      consulted). d. Parse args, validate typed inputs, render Jinja2 / legacy placeholders. e. Substitute the expansion
      back into the prompt.
   5. **Unmask fences and disabled regions.**
   6. **Extract directives** in the launcher path via `extract_prompt_directives` (`preprocessing.py` line 101) — this
      runs _after_ full xprompt expansion, not as part of the same render step.

   The diagram orders the chips as: Mask → Parse → Apply aliases → Discovery → Validate → Render Jinja2 + directives.
   That is wrong on three counts: aliases come **first** (not third), fenced/disabled masking happens after aliases (not
   before), and directives are **not** rendered together with Jinja2 — they are extracted by a separate post-expansion
   call.

2. **"Apply aliases" is misplaced.** Per `processor.py:264` and the doc's XPrompt Aliases section, alias substitution
   runs first, not after parsing. As drawn, the diagram tells a new reader the resolver finds `#c` in the prompt, then
   _later_ swaps it for `#commit`, which would mean alias names need to exist as xprompts during parse — they don't.
3. **Recursive iterative expansion is missing.** The resolver iterates up to 100 times until no more references are
   found (`_MAX_EXPANSION_ITERATIONS = 100` at `processor.py:40`; doc's Recursive Expansion section). The diagram shows
   a straight-line pipeline with no loop arrow.
4. **Directives are not part of the Jinja2 render step.** They are a separate extract pass that runs _after_ the xprompt
   expansion completes (`preprocessing.py` lines 80–101: `process_xprompt_references` is called, then
   `extract_prompt_directives` is called on its output). The doc's Directives section says "they are extracted and
   stripped from the prompt before further processing" — which refers to the _agent runner_, but the action still
   happens after xprompt expansion. Combining "Jinja2" and "directives" into one chip overstates how integrated they are
   and obscures that directives operate on the post-expansion text (which is why `%alt` etc. can fan out on the final
   prompt body).
5. **Command substitution `$(cmd)` is missing entirely.** `docs/xprompt.md` "Command Substitution" documents `$(cmd)`
   argument substitution, including nested-paren handling and the per-pass cache. It is a real argument-time step (the
   xprompt arg parser executes `$(...)` segments) and worth at least one chip — its omission is conspicuous given that
   `%directives` got its own input row.
6. **Discovery-stack label set is wrong.** `docs/xprompt.md` documents the priority slots: `.xprompts/` CWD hidden,
   `xprompts/` CWD, `~/.xprompts/`, `~/xprompts/`, `~/.config/sase/xprompts/{project}/`, `sase.yml xprompts:`, plugin
   packages, `<sase_package>/default_xprompts/*.md`, and `<sase_package>/xprompts/*.md`. The diagram's discovery stack
   shows five rungs labeled `project-local`, `user/project`, `config`, `plugins`, `6 built-in`. Issues with that:
   - The "6 built-in" rung is wrong: there are **two** built-in priorities (priorities 9 and 10), not six. Reading "6
     built-in" as "six built-in entries" misleads about how many built-in xprompts ship.
   - `.xprompts/` (CWD hidden) and `xprompts/` (CWD) collapse into "project-local"; `~/.xprompts/`, `~/xprompts/`, and
     `~/.config/sase/xprompts/{project}/` collapse into "user/project" — this is a defensible compression, but the
     remaining rungs do not match the documented vocabulary.
7. **The `keyword trigger` input row is obsolete.** The arrow direction implied by placing it in the input column is
   "user prompt → resolver", but that legacy injection feature has been removed. The row should be deleted from the next
   diagram instead of moved elsewhere.
8. **Workspace references are documented as running first, but the pipeline doesn't reflect that.** From the "VCS
   Workspace References" section: prompts without a workspace reference are normalized to `#git:home`, and the workspace
   reference is applied _before_ the rest of the prompt runs. The diagram's caption "workspace selection first" hints at
   this but no chip in the resolution column captures it. A leading chip (or pre-pipeline branch) labeled "Workspace ref
   dispatch (`#cd`/`#git`/`#gh`/`#hg`)" would close the gap. Bonus accuracy: the implicit `#git:home` normalization for
   bare prompts is a real behavior worth mentioning, and it is exactly the kind of defaulting a new reader misses.
9. **Multi-agent fan-out is "one-level split into agents", but recursive multi-agent fan-out is bounded, not
   prohibited.** The doc says "Recursive fan-out (a multi-agent xprompt body whose own segments reference more
   multi-agent xprompts) is bounded by a depth cap and will raise if exceeded." "One-level" is a small accuracy slip —
   it is not strictly one level, just depth-capped.
10. **`#` / `#!` semantics need to stay current.** The `#!workflow` input card should stay limited to standalone YAML
    workflows. Markdown-defined multi-agent xprompts use the normal `#name` marker and fan out at launch when their body
    has top-level `---` separators.

## Concrete suggested changes for regeneration

For the next phase (`sase-2s.18 — Regenerate diagram: xprompt-resolution`):

1. **Reorder the resolution pipeline to match `processor.py`**, with the canonical chip list, top to bottom, with an
   explicit loop arrow on the iterating section:
   `Apply aliases (text-level) → Mask fences + disabled regions → [loop until no refs: Parse references → Look up via discovery order → Validate typed inputs → Render Jinja2/legacy → Substitute] → Unmask → Extract directives`.
   Mark the parse/lookup/render section with a circular arrow captioned "iterate ≤100 passes" so recursive expansion is
   visible.
2. **Separate "Render Jinja2" from "Extract directives".** Make them two distinct chips. Directive extraction sits
   _outside_ (after) the xprompt expansion loop and operates on the fully expanded text.
3. **Add a "Workspace ref dispatch" pre-stage** that runs before the resolution pipeline, with the implicit `#git:home`
   default annotated. Wire it from the `#cd / #gh refs` input card.
4. **Add a "Command substitution `$(cmd)`" chip** as a sub-step on the parse-args edge (or as a small annotation on
   "Validate typed inputs"). It is real, it is documented, and its omission is conspicuous.
5. **Replace the `Discovery stack` side bar with the documented priority list** (or a faithfully-collapsed version that
   disambiguates the two built-in slots). Drop the misleading "6 built-in" rung.
6. **Remove the "keyword trigger" row from the input column** because that legacy injection feature is no longer part of
   xprompt resolution.
7. **Wire the `Fences + disabled regions` callout into the Mask stage** with an explicit arrow, so the relationship
   between the protective syntax and the masking step is visible.
8. **Re-caption the `%directives` input card** with the documented categories: `launch overrides`, `scheduling`,
   `fan-out` — not "append, override, repeat".
9. **Rename the `Inline prompt_part` output card to `Inline expansion`** (or `Inline prompt fragment`) to match
   `docs/xprompt.md` reader-facing terminology, and reserve `prompt_part` for internal docs.
10. **Visually demote the `Workflow graph` output card** (or annotate it `(via sase xprompt graph)`) so it does not read
    as a runtime peer of inline/standalone/fan-out outcomes.
11. **Clarify the marker rows** to show `#name — inline xprompt / embeddable workflow / multi-agent xprompt` and
    `#!name — standalone workflow` so the multi-agent fan-out output is tied to `#name`, not `#!name`.
12. **Soften the `Multi-agent fan-out` output caption** from "one-level split into agents" to "fan-out into agent
    segments (depth-capped)" so it doesn't read as a hard one-level rule.

These changes bring the diagram into alignment with `docs/xprompt.md`, the actual order in
`src/sase/xprompt/processor.py`, and the post-expansion directive-extract step in
`src/sase/llm_provider/preprocessing.py`.
