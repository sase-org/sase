---
create_time: 2026-05-04 13:43:10
status: done
prompt: sdd/prompts/202605/legend_bead_integration.md
bead_id: sase-21
tier: epic
---
# Improve Legend Bead Integration

## Goal

Make legend beads executable kickoff points for their proposed epics.

When a legend plan is approved, the follow-up `#bd/new_legend` agent should create a legend-tier plan bead, record how
many epics the legend proposes, commit that metadata, and then run `sase bead work <legend_bead_id> --yes`. The
`sase bead work` command should recognize legend-tier plan beads and launch one epic-planning agent per proposed epic,
without launching them before the legend bead is explicitly worked.

Each launched epic-planning agent should:

- be named `<prj>-<M>.<N>.0`, where `<prj>-<M>` is the legend bead ID and `<N>` is the 1-based epic number from the
  legend plan;
- use a prompt shaped like the `sase ace` snapshot: VCS prefix when available, optional wait directive, request to
  implement/create epic `#<N>` from the legend plan file, `#epic`, and `%name:<agent_name>`;
- include `%epic` so the created plan is auto-approved as an epic;
- wait on the prior epic's land agent for all epics after the first, using `%w:<prj>-<M>.<N-1>`;
- not create phase beads directly; that remains the responsibility of the spawned epic-creation flow and existing
  `bd/new_epic` automation.

## Current Shape

Epic automation already exists in `src/sase/bead/cli_work.py` and `src/sase/bead/work.py`. It validates an epic-tier
plan bead, builds a Rust-backed phase DAG plan via `../sase-core/crates/sase_core/src/bead/work.rs`, renders a
`---`-separated multi-prompt, pre-claims phase beads, marks `is_ready_to_work`, and launches via
`launch_agent_from_cwd()`.

Legend approval already routes to `#bd/new_legend:<plan_ref>` from `src/sase/axe/run_agent_exec_plan.py`. The built-in
`bd/new_legend` xprompt currently tells the agent to create exactly one legend bead and explicitly says not to run
`sase bead work`, so legend execution is intentionally missing today.

Bead storage is Rust-backed. Shared bead schema and behavior belong in `../sase-core/crates/sase_core`, with Python
model/facade/parser updates in this repo.

## Phase 1: Legend Epic Count Metadata

Owner: one agent, focused on schema/model/CLI/read-write support.

Add first-class metadata for the number of epics proposed by a legend bead.

Implementation scope:

- Add an optional integer field, recommended name `epic_count`, to the bead issue model and wire records.
- Persist it in JSONL and the compatibility SQLite schema/migrations in both Python and Rust.
- Validate it conservatively:
  - only plan beads may carry it;
  - only `tier=legend` should carry a non-null value;
  - value must be a positive integer when set.
- Add `-E/--epic-count` to `sase bead create` and `sase bead update`, preserving the repo convention that CLI options
  have short flags.
- Thread the field through `BeadProject.create/update`, Rust mutation/read facades, `IssueWire`, Python `Issue`, and
  JSONL import/export.
- Update display/query behavior only where needed so `sase bead show <legend>` exposes the field and tests can assert
  it.

Tests:

- Rust unit/schema tests for defaulting, serde compatibility, validation, and migration detection.
- Python model/facade/project tests for create/update/show/list round trip.
- CLI tests for `--epic-count`, invalid tier/type combinations, and invalid counts.

Exit criteria:

- Existing epic work automation behavior is unchanged.
- Old bead JSONL without `epic_count` still loads.
- A command like `sase bead create -t "Roadmap" -T plan(sdd/legends/202605/roadmap.md) --tier legend --epic-count 5`
  stores and shows the count.

## Phase 2: Legend Work Planner And Renderer

Owner: one agent, focused on launch planning and prompt rendering, building on Phase 1.

Add a separate legend-work planning path rather than overloading the epic phase DAG planner.

Implementation scope:

- Add Rust core planning for legend work, likely beside the current epic work planner:
  - validate the target exists, is `issue_type=plan`, and has `tier=legend`;
  - require `epic_count` to be present and positive;
  - require the legend bead design/plan path to be present;
  - produce deterministic assignments for epic numbers `1..epic_count`.
- Define a Python-facing `LegendWorkPlan` and `LegendEpicAssignment` in `src/sase/bead/work.py`.
- Agent names should be exactly `<legend_id>.<N>.0`.
- Wait chain should be linear:
  - epic 1 waits on nothing;
  - epic N waits on `<legend_id>.<N-1>` for N > 1, because the prior epic's land agent is named `<legend_id>.<N-1>`.
- Render a multi-prompt shaped like the snapshot:
  - optional VCS wrapper prefix, same regular project inference used by epic work;
  - `%name:<legend_id>.<N>.0`;
  - `%approve`;
  - `%epic`;
  - `%w:<legend_id>.<N-1>` for N > 1;
  - `Can you help me implement epic #<N> from the roadmap in the <plan_file> file? #epic Keep in mind ...`;
  - keep the plan-file language close to the snapshot but avoid hard-coding “roadmap” if the existing product vocabulary
    prefers “legend plan”.
- Do not add `bd/new_epic` directly to these prompts. These agents create plans, and `%epic` should trigger the existing
  epic follow-up path after their plans are approved automatically.
- Reuse existing VCS project context detection from `cli_work.py`; ChangeSpec launch context is not required for legend
  work unless a later explicit requirement asks for it.
- Add live-name collision checks for the generated `.0` agents and legacy/land names if any are introduced.

Tests:

- Rust planner tests for count validation, naming, wait chain, missing design path, non-legend rejection, and
  deterministic output.
- Python render snapshot tests for no VCS and VCS contexts.
- Tests that the rendered prompt contains `%epic`, `%approve`, `%name:<legend_id>.<N>.0`, and the expected `%w` chain.

Exit criteria:

- `sase bead work <legend_id> --dry-run` prints a multi-prompt with one epic-planning segment per stored epic count.
- No phase beads are created or claimed in legend dry runs or live runs.

## Phase 3: Integrate `sase bead work` For Legend Beads

Owner: one agent, focused on CLI control flow and rollback semantics.

Extend the existing `handle_bead_work` dispatcher to route by plan tier.

Implementation scope:

- Keep current epic behavior intact for `tier=epic`.
- For `tier=legend`:
  - build the legend work plan;
  - mark the legend bead `is_ready_to_work` when launching, with rollback on launch failure;
  - do not pre-claim child beads, since the children do not exist yet;
  - launch the rendered multi-prompt via `launch_agent_from_cwd()`;
  - support `--dry-run` and `--yes` with behavior parallel to epic work.
- Update errors and summary text so users see “Legend `<id>`: N epic agent(s)” rather than epic/phase language.
- Preserve re-entry semantics: if the legend is already ready, allow retrying launch after collision checks and print
  clear retry text.
- Decide whether to reject `epic_count` mismatch with existing linked epic children in this phase or defer it.
  Recommended: in this phase, only use stored `epic_count`; do not infer from children, because the requirement says the
  `#bd/new_legend` agent must specify the count.

Tests:

- CLI dry-run does not mutate or launch.
- Live launch marks legend ready and calls launcher once with the rendered multi-prompt.
- Launch failure rolls back only `is_ready_to_work`.
- Already-ready legend can retry.
- Epic-tier tests remain unchanged.
- Non-plan and plain-plan tiers still get clear errors.

Exit criteria:

- `sase bead work` supports both epic and legend plan beads with distinct summaries and correct launch behavior.
- Existing epic work tests still pass without snapshot churn unrelated to the feature.

## Phase 4: Update Built-In XPrompts And Follow-Up Flow

Owner: one agent, focused on prompt contracts.

Update the user-facing automation prompts so legend approval records the required count and triggers the new legend work
path at the right time.

Implementation scope:

- Update `bd/new_legend` in `src/sase/default_config.yml`:
  - instruct the agent to count the epics proposed by the legend plan file;
  - create the legend bead with `--tier legend --epic-count <count>`;
  - write `legend_bead_id`, `tier: legend`, and the same count field to plan frontmatter;
  - commit bead and plan metadata;
  - after committing, run `sase bead work <legend_bead_id> --yes`.
- Remove the old “Do not run `sase bead work`” instruction.
- Update xprompt tag tests that assert the current `bd/new_legend` body.
- Update `src/sase/xprompts/skills/sase_beads.md`, docs, and onboarding text to document legend beads, `--epic-count`,
  and `sase bead work <legend_id>`.
- Ensure the existing legend approval path in `run_agent_exec_plan.py` can stay unchanged: it should still spawn
  `#bd/new_legend:<legend_plan_ref>`, and the xprompt now performs the delayed launch only after the bead exists and is
  committed.

Tests:

- Built-in prompt registry test confirms `bd/new_legend` mentions `--epic-count`, frontmatter count, and
  `sase bead work <legend_bead_id> --yes`.
- Xprompt rendering tests confirm the plan path argument still works.
- Existing `test_axe_run_agent_exec_plan_followups.py` remains valid or gets minimal assertion updates for the changed
  prompt contract.

Exit criteria:

- Legend agents are not created by the original plan-approval follow-up itself.
- Legend agents are created only after the `#bd/new_legend` agent runs `sase bead work <legend_bead_id> --yes`.

## Phase 5: End-To-End Validation And Polish

Owner: one agent, focused on integration confidence and edge cases.

Close gaps across the full legend-to-epic automation path.

Implementation scope:

- Add an integration test that simulates:
  - legend bead creation with `epic_count=3`;
  - `sase bead work <legend_id> --dry-run`;
  - expected prompts for `<legend_id>.1.0`, `<legend_id>.2.0`, `<legend_id>.3.0`;
  - `%w:<legend_id>.1` and `%w:<legend_id>.2` chaining;
  - `%epic` in every segment.
- Add a live-launch mocked test that verifies `launch_agent_from_cwd()` receives exactly one multi-prompt and no child
  beads are created.
- Run focused Python and Rust tests first, then `just install` if needed and `just check` before final handoff.
- Update any SDD prompt/status frontmatter needed for the implementation work, but avoid broad unrelated doc churn.

Exit criteria:

- The feature is demonstrable with dry-run output.
- `just check` passes.
- The final behavior matches the snapshot-style prompt contract and the delayed-launch requirement.

## Open Design Decisions

Recommended decisions for implementation agents:

- Use `epic_count` as the persisted bead field and frontmatter field. It is concise and clear within a legend-tier bead
  context.
- Use `-E` as the short CLI flag for `--epic-count`, since `-e` is likely to be confused with existing edit/epic
  concepts and all CLI flags need short options.
- Keep legend work as a separate planner/rendering code path. Epic work is DAG-based over existing phase children;
  legend work is count-based over not-yet-existing epics.
- Do not add a final “land legend” agent in this feature. The requested wait chain says each epic after the first waits
  for the agent that lands the previous epic, and does not request a final legend-close agent.
- Do not infer `epic_count` from markdown headings in `sase bead work`; the count should be explicitly stored by
  `#bd/new_legend` so the launch behavior is deterministic and inspectable.
