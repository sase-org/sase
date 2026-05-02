---
create_time: 2026-05-02 00:34:15
status: done
bead_id: sase-1z
tier: epic
prompt: sdd/prompts/202605/docs_gpt_image_infographics.md
---

# Plan: GPT Image Infographics for High-Complexity Docs

## Goal

Generate and embed infographics for five Markdown files in `docs/` where a visual diagram will materially improve
comprehension. The work should use GPT image generation for the visual assets, keep the final docs maintainable, and be
split so each phase can be handled by a distinct agent instance.

The selected docs are:

1. `docs/xprompt.md` — explains discovery precedence, reference parsing, inline vs standalone workflows, directives,
   protected content, dynamic memory, and multi-agent fan-out. This is the densest conceptual surface in `docs/`.
2. `docs/workflow_spec.md` — defines the YAML execution model: inputs, environment, step types, artifacts, control flow,
   parallel execution, joins, templates, and HITL. A pipeline diagram will help readers orient before diving into
   syntax.
3. `docs/commit_workflows.md` — describes an end-to-end orchestration path from agent changes through stop hooks, commit
   skills, `CommitWorkflow`, VCS dispatch, ChangeSpec/COMMITS tracking, and conflict resume.
4. `docs/beads.md` — combines data model, storage model, dependency readiness, Rust-backed mutation/query behavior,
   multi-workspace merging, and `sase bead work` epic fan-out. It benefits from a lifecycle and execution map.
5. `docs/rust_backend.md` — documents the Python facade/Rust extension boundary, Rust-owned vs Python-owned behavior,
   health checks, contracts, and migration history. A boundary infographic will reduce ambiguity.

Not selected for the first pass:

- `docs/axe.md` already contains a useful architecture ASCII diagram; it is a good follow-up candidate, but the five
  above have more unresolved visual load.
- `docs/llms.md`, `docs/mentors.md`, `docs/plugins.md`, and `docs/vcs.md` would also benefit from visuals, but they are
  either more reference-oriented or overlap with the selected docs' plugin/provider concepts.
- `docs/ace.md` is very long, but it is largely a user-guide/keybinding reference; screenshots or terminal captures
  would be more useful than GPT-generated infographics.

## Asset Policy

Use `docs/images/` for final assets, matching the existing docs asset location. Suggested final filenames:

- `docs/images/xprompt-resolution-infographic.png`
- `docs/images/workflow-execution-infographic.png`
- `docs/images/commit-workflow-infographic.png`
- `docs/images/bead-epic-work-infographic.png`
- `docs/images/rust-backend-boundary-infographic.png`

For each image, add a source prompt sidecar next to the image:

- `docs/images/xprompt-resolution-infographic.prompt.md`
- `docs/images/workflow-execution-infographic.prompt.md`
- `docs/images/commit-workflow-infographic.prompt.md`
- `docs/images/bead-epic-work-infographic.prompt.md`
- `docs/images/rust-backend-boundary-infographic.prompt.md`

Each sidecar should include:

- the final GPT image prompt
- the target doc section where the image is embedded
- the intended alt text
- any manual post-processing notes, especially if deterministic labels were added after generation

Use relative Markdown links from each doc, for example:

```markdown
![XPrompt resolution pipeline](images/xprompt-resolution-infographic.png)
```

Alt text should be useful on its own and should not merely repeat the title. Keep each image near the first major
conceptual overview section, before long reference tables.

## Visual Direction

Use a consistent documentation style across all five images:

- clear architecture infographic, not marketing art
- light or neutral background with enough contrast for dark text
- restrained color palette with distinct colors for concepts, not a one-hue theme
- landscape composition suitable for GitHub Markdown, roughly 16:9
- crisp arrows, swimlanes, and blocks
- no logos for third-party products unless already present in text and necessary
- no tiny text, no fake terminal screenshots, and no dense paragraphs inside the raster image

Generated text in raster images is unreliable. Each phase should first try a prompt that asks for short, legible labels,
then inspect the result. If labels are wrong, misspelled, or too soft, keep the generated layout/illustration only and
add labels deterministically in a simple local post-processing step. The final committed image should be readable
without relying on nearby prose.

## Phase 1: Shared Visual Brief and Candidate Validation

Owner: distinct agent instance.

Objective: create the shared visual contract for the five infographic agents and validate that the selected insertion
points still match the docs.

Scope:

- Re-read the selected docs' opening and architecture/lifecycle sections.
- Confirm or adjust exact insertion points:
  - `docs/xprompt.md`: after the introductory "Use xprompts when you want to" list or before "CLI Subcommands".
  - `docs/workflow_spec.md`: after the opening paragraph or before "Top-Level Structure".
  - `docs/commit_workflows.md`: after "Overview" and before "How It Works", or immediately after the workflow table.
  - `docs/beads.md`: after "Data Model" intro or before "Quick Start" if the image should orient users first.
  - `docs/rust_backend.md`: before "Why a Rust Backend?" or at the start of "Architecture".
- Write or update a short shared brief, preferably as a section in the plan follow-up notes or as
  `docs/images/infographic-style-brief.md`, only if later agents need a stable source of truth.
- Do not generate final images in this phase unless doing so is explicitly useful for validating style.

Exit criteria:

- The five selected docs and insertion points are confirmed.
- Any style brief is concise and does not become a new maintenance burden.
- No target Markdown docs are edited yet unless this phase intentionally creates only shared supporting notes.

## Phase 2: `docs/xprompt.md` Infographic

Owner: distinct agent instance.

Objective: generate and embed an infographic showing how xprompt references become final prompts or launched workflows.

Concept:

- left side: user prompt with `#name`, `#!workflow`, `%directives`, workspace refs, and dynamic memory triggers
- middle: resolution stages: protect fenced/disabled regions, parse references, resolve discovery order, apply aliases,
  validate typed inputs, render Jinja2, attach dynamic memory, split multi-agent prompts
- right side: outputs: inline prompt fragment, standalone workflow execution, workflow graph, or multi-agent fan-out
- include a small discovery-priority stack: project-local, user config, config, plugins, built-ins

Scope:

- Generate `docs/images/xprompt-resolution-infographic.png` with GPT image.
- Add `docs/images/xprompt-resolution-infographic.prompt.md`.
- Embed the image in `docs/xprompt.md` near the top-level conceptual overview.
- Keep surrounding prose minimal: one sentence can introduce the diagram if needed.
- Verify all labels match terminology used by the doc: "xprompt", "standalone workflow", "prompt_part", "dynamic
  memory", "directives", "multi-agent".

Exit criteria:

- The final image is readable at typical GitHub Markdown width.
- The sidecar prompt exists and describes any post-processing.
- `docs/xprompt.md` references the image with useful alt text.

## Phase 3: `docs/workflow_spec.md` Infographic

Owner: distinct agent instance.

Objective: generate and embed an infographic showing the workflow execution model.

Concept:

- input parameters and environment flow into ordered steps
- step types: agent, prompt_part, bash, python, hidden, parallel
- artifacts and outputs pass between steps through named fields
- control flow wraps steps: `if`, `for`, `while`, `repeat/until`
- parallel branches join via object/array/text/lastOf join modes
- HITL gates can pause before proceeding

Scope:

- Generate `docs/images/workflow-execution-infographic.png` with GPT image.
- Add `docs/images/workflow-execution-infographic.prompt.md`.
- Embed the image in `docs/workflow_spec.md` near the opening overview.
- Confirm the diagram does not imply unsupported nesting or execution semantics. In particular, avoid showing
  `prompt_part` as a separate LLM call.

Exit criteria:

- The image correctly distinguishes prompt injection from agent execution.
- The image makes parallel/join behavior visible without overloading readers.
- `docs/workflow_spec.md` references the image with useful alt text.

## Phase 4: `docs/commit_workflows.md` Infographic

Owner: distinct agent instance.

Objective: generate and embed an infographic showing the shared commit/propose/PR path.

Concept:

- agent receives `#commit`, `#propose`, or `#pr`
- stop hook detects uncommitted changes and blocks with commit-skill instruction
- `/sase_git_commit` or equivalent skill calls `sase commit`
- `CommitWorkflow` stages: precommit, bead lifecycle, plan handling, PR tags, parent detection, VCS dispatch, tracking,
  result marker
- branch into the three outputs:
  - commit hash + COMMITS entry
  - saved diff + COMMITS entry
  - PR URL + ChangeSpec entry
- include conflict checkpoint/resume as a side loop

Scope:

- Generate `docs/images/commit-workflow-infographic.png` with GPT image.
- Add `docs/images/commit-workflow-infographic.prompt.md`.
- Embed the image in `docs/commit_workflows.md` after the overview table or before "How It Works".
- Verify terminology stays VCS-agnostic enough to cover git, GitHub, and Mercurial where the doc does.

Exit criteria:

- The three workflow outputs are visually distinct.
- Conflict resume is shown as recoverable checkpoint/resume, not as a normal success path.
- `docs/commit_workflows.md` references the image with useful alt text.

## Phase 5: `docs/beads.md` Infographic

Owner: distinct agent instance.

Objective: generate and embed an infographic showing bead planning, dependency readiness, storage, and epic execution.

Concept:

- plan bead tiers: plan, epic, legend
- phases as child beads with hierarchical IDs
- dependency edges determine ready vs blocked work
- SQLite local query cache and JSONL git-portable export stay synchronized through Rust mutations
- `sase bead work <epic>` creates Kahn waves, pre-claims phases, launches one agent per phase, and launches a final land
  agent waiting on leaf phases
- multi-workspace reads merge sibling workspaces while writes go to primary

Scope:

- Generate `docs/images/bead-epic-work-infographic.png` with GPT image.
- Add `docs/images/bead-epic-work-infographic.prompt.md`.
- Embed the image in `docs/beads.md` near the start, likely before "Quick Start" or between "Quick Start" and "Data
  Model".
- Keep text labels short. The image should not attempt to reproduce the full CLI command table.

Exit criteria:

- The image clearly separates the issue data model from the epic execution flow.
- The Rust-backed SQLite/JSONL storage relationship is accurate.
- `docs/beads.md` references the image with useful alt text.

## Phase 6: `docs/rust_backend.md` Infographic

Owner: distinct agent instance.

Objective: generate and embed an infographic showing the Python/Rust boundary and ownership model.

Concept:

- top layer: `sase` Python UI/CLI/TUI/workflow host logic
- middle layer: `sase.core` Python facade and stable wire records
- bottom layer: required `sase_core_rs` PyO3 extension and sibling `sase-core` Rust workspace
- Rust-owned operation groups: parsing/query corpus, notifications store, status planning, agent scan/cleanup/launch
  planning, bead reads/mutations/work DAG, git query parsers
- Python-owned host responsibilities: file-path APIs, VCS/workspace plugins, xprompt resolution, user prompts, process
  orchestration, TUI rendering, side-effecting transitions
- health/contract loop: `sase core health`, golden fixtures, focused Python/Rust tests

Scope:

- Generate `docs/images/rust-backend-boundary-infographic.png` with GPT image.
- Add `docs/images/rust-backend-boundary-infographic.prompt.md`.
- Embed the image in `docs/rust_backend.md` at the "Architecture" section.
- Avoid using wording that suggests Python fallbacks for required Rust-owned operations; the doc explicitly says there
  is no pure-Python fallback.

Exit criteria:

- The image makes ownership boundaries obvious.
- The health/contract test loop is present but secondary.
- `docs/rust_backend.md` references the image with useful alt text.

## Phase 7: Cross-Doc QA and Polish

Owner: distinct agent instance.

Objective: review the five completed infographics together for consistency, readability, and documentation quality.

Scope:

- Inspect all five images at full size and at GitHub-like rendered width.
- Check for hallucinated labels, misspellings, incorrect arrows, inconsistent terminology, or unreadable text.
- Confirm every sidecar prompt exists and matches the final image.
- Confirm Markdown links are relative and valid.
- Run a link/file existence check over the edited docs.
- If available, render Markdown locally or use a lightweight preview to confirm image sizing and placement.
- Keep any corrections tightly scoped to the images, sidecars, and five target docs.

Exit criteria:

- All image files referenced by the five Markdown docs exist.
- All five images share a coherent visual language.
- The docs still read well without the images, and the images add orientation instead of duplicating entire sections.
- Run `just install` if needed, then `just check` in this repo before final handoff, because repo instructions require
  `just check` after file changes.

## Verification Strategy

Each implementation phase should do at least:

```bash
rg -n "images/.*infographic\\.png|!\\[" docs/*.md
test -f docs/images/<expected-image>.png
test -f docs/images/<expected-image>.prompt.md
```

The final QA phase should additionally run:

```bash
just install
just check
```

If `just check` is too slow or blocked by missing local dependencies, the responsible agent should report the exact
failure and run narrower validation for Markdown links and touched files.

## Risks and Mitigations

- Raster text quality: prefer short labels; inspect every image; add deterministic labels if needed.
- Generated semantic drift: each phase must cross-check terms against the target doc before embedding.
- Inconsistent style: Phase 1 establishes the shared visual brief; Phase 7 performs cross-image polish.
- Oversized binary churn: commit only final PNGs and prompt sidecars, not every rejected generation.
- Maintenance burden: prompt sidecars make future regeneration possible without requiring prior chat history.
