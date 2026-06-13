---
create_time: 2026-06-13 09:55:30
bead_id: sase-4n
tier: epic
status: done
prompt: sdd/prompts/202606/plan_command_subcommands.md
---
# Improve `sase plan` Command

## Goal

Turn `sase plan` into a command group:

- `sase plan propose <plan_file>` owns the existing plan-submission behavior.
- `sase plan approve` approves a pending proposed plan from the CLI.
- `sase plan list` shows the current plan pipeline, and bare `sase plan` defaults to `list`.
- The generated `/sase_plan` skill source is updated so future agents submit with `sase plan propose`.

This should preserve the existing agent-runner protocol instead of inventing a parallel one: proposal still archives the
plan and writes `.sase_plan_pending`; approval still writes `plan_response.json`; plan approval metadata remains in
`agent_meta.json`; SDD plan archiving keeps using the existing approval side effects.

## Important Existing Behavior

- Current `sase plan <plan_file>` lives in `src/sase/main/plan_command_handler.py`.
- It requires `SASE_AGENT` and `SASE_ARTIFACTS_DIR`, formats the plan with Prettier, copies it into sharded
  `~/.sase/plans/YYYYMM/`, writes `.sase_plan_pending`, pulses ACE with `.ace_refresh_pulse`, and terminates the runner
  group.
- Plan approval notifications use action `PlanApproval`, `action_data.response_dir`, and a `plan_request.json` /
  `plan_response.json` protocol.
- Approved plan state is persisted to `agent_meta.json` as `plan_approved: true` and `plan_action`.
- The original archived proposal path is recorded in agent metadata as `plan_path`; SDD committed copies may appear as
  `sdd_plan_path`.
- Skill files are generated from `src/sase/xprompts/skills/*.md`; do not hand-edit live chezmoi skill outputs.
- CLI rules require excellent help, sorted subcommands/options, short aliases for public long options, and colored
  output where useful.

## Design Decisions

### Command Shape

`sase plan` becomes an argparse command group with sorted children:

- `approve`: approve one pending proposed plan.
- `list`: show plan proposal/approval history; default child for bare `sase plan`.
- `propose`: submit a plan file for approval, replacing the old positional root command.

Avoid keeping `sase plan <file>` as a hidden compatibility path unless an implementation agent finds a strong migration
reason. If a compatibility guard is cheap, prefer a clear error such as `Use: sase plan propose <file>`.

### `sase plan approve`

The CLI should approve pending `PlanApproval` notifications by writing the same `plan_response.json` shape used by ACE
and the mobile gateway.

Recommended UX:

- `sase plan approve [selector]`
- If `selector` is omitted and exactly one pending proposal exists, approve that proposal.
- If zero or multiple pending proposals exist, exit with a concise error and tell the user to run `sase plan list`.
- `selector` should accept the notification ID or unique prefix shown by `sase plan list`; path/basename matching is
  nice if straightforward, but not required for the first complete version.
- Add `-k|--kind` with choices:
  - `approve`: no SDD commit; run coder. This matches ACE's `a` key.
  - `tale`: commit to `sdd/tales`; run coder. This matches ACE's `t` key.
  - `epic`: commit to `sdd/epics`; launch epic-bead follow-up.
  - `legend`: commit to `sdd/legends`; launch legend-bead follow-up.
  - `commit`: commit the plan without launching coder, using the existing `run_coder=false` protocol.
- Add `-p|--prompt` for optional coder prompt text.
- Add `-m|--model` for optional coder model.

Implementation should reuse or extract the existing mobile plan action code rather than duplicate protocol mapping and
side effects. If reused directly, extend it to understand `tale` and `commit` so CLI, mobile, and ACE semantics line up.

### `sase plan list`

Build a read-only inventory service first, then render it. The command should have a beautiful Rich default view and may
also support `-j|--json` for tests/scripts.

Classify plans as:

- Proposed: active pending `PlanApproval` notifications where the response target is still available. Show all of them.
- Approved: `agent_meta.json` records with `plan_approved: true`, sorted by the best available approval time, limited to
  the 10 most recent across all projects.
- Rejected: markdown files under sharded `~/.sase/plans/` whose normalized path is not represented by the proposed set
  or approved set, sorted by file mtime, limited to the 10 most recent. This is intentionally inferred from the user's
  definition.

Render as a compact dashboard:

- Summary panel: counts for proposed, approved shown, rejected shown, and total archived proposals.
- Proposed table: ID prefix, age, agent/project, provider/model when known, plan path.
- Approved table: approved age/time, action (`approve`, `tale`, `epic`, `legend`, `commit`), agent/project, plan path.
- Rejected table: age/time, plan path, note that this is inferred from unrepresented archived proposals.
- Empty sections should still look intentional, e.g. dim text inside a panel.

Use stable columns and folded paths so wide absolute paths do not make the display ugly.

## Phases

### Phase 1: Command Group Migration and Skill Contract

Scope:

- Convert `register_plan_parser` into a command group with `approve`, `list`, and `propose` children.
- Move existing root positional behavior to `sase plan propose <plan_file>`.
- Rename or wrap `handle_plan_command` so the code reads as `handle_plan_propose_command` while preserving existing
  logic.
- Add a `handle_plan_command(args)` dispatcher like `skills_handler`.
- Update entry-point dispatch from `handle_plan_command(args.plan_file)` to the new dispatcher.
- Update user-facing errors/help text from `sase plan` to `sase plan propose`.
- Update `src/sase/xprompts/skills/sase_plan.md` to submit with: `sase plan propose sase_plan_<name>.md`
- Run `sase init-skills --force` and `chezmoi apply` so generated skill files match the source.

Tests:

- Parser tests for `sase plan`, `sase plan list`, `sase plan propose file.md`, and `sase plan approve`.
- Handler tests updated from `sase plan` wording to `sase plan propose`.
- Skill/source test that `/sase_plan` examples use `sase plan propose`.
- Help-output regression covering sorted subcommands.

Exit criteria:

- Existing proposal behavior is unchanged except for the new command path.
- Bare `sase plan` parses as list.
- Future agents using `/sase_plan` submit via `sase plan propose`.

### Phase 2: Plan Inventory and Beautiful List UI

Scope:

- Add a small plan inventory module, likely under `src/sase/plan/` or `src/sase/main/plan_*`, with dataclasses for
  proposed, approved, rejected, and overall inventory.
- Proposed inventory reads notification snapshots and uses the same pending-action/action-state rules as the mobile
  gateway.
- Approved inventory scans `~/.sase/projects/*/artifacts/**/agent_meta.json` or an existing indexed agent snapshot if
  available and reliable. Prefer normalized `plan_path`, falling back to `sdd_plan_path`.
- Rejected inventory scans `iter_sharded_files("plans", pattern="*.md")` and subtracts normalized proposed/approved
  paths.
- Add a Rich renderer for `sase plan list`; default bare `sase plan` uses it.
- Add `-j|--json` if practical; keep the pretty Rich dashboard as the default.

Tests:

- Unit tests for classification with a temp `SASE_HOME`: multiple pending proposals, approved agent metas, and archived
  plans that become inferred rejects.
- Dedupe tests for the same plan path appearing in multiple records.
- Limit tests: all proposed, 10 approved, 10 rejected.
- Rich output snapshot/string tests with a fixed-width non-color console.
- JSON schema test if `-j|--json` is added.

Exit criteria:

- `sase plan` and `sase plan list` are useful and attractive even in empty state.
- The inferred rejected bucket exactly follows: archived plans not represented by proposed or approved groups.

### Phase 3: CLI Approval Path

Scope:

- Implement `sase plan approve [selector]`.
- Resolve selector through pending action notification IDs/prefixes; support omitted selector only when one pending plan
  exists.
- Map `-k|--kind` choices to the existing runner response protocol.
- Write `plan_response.json` with exclusive creation so duplicate approvals fail clearly.
- Mark the notification dismissed best-effort and run the same plan side effects used by mobile/ACE:
  - persist `plan_approved` and `plan_action` to `agent_meta.json`;
  - archive approved plan copies into SDD when applicable;
  - update `saved_plan_path` in the response when an SDD copy is written;
  - refresh the artifact index after metadata changes.
- Keep unsupported features out of scope unless they fall out naturally; `reject` is not required by this request.

Tests:

- Approve by unique prefix writes correct JSON for `approve`, `tale`, `epic`, `legend`, and `commit`.
- Omitted selector succeeds with one pending proposal and errors with zero/multiple.
- Duplicate response file returns a conflict without overwriting.
- Missing request/response directories produce actionable errors.
- Side-effect tests cover `agent_meta.json` persistence and SDD archive path updates, ideally by sharing existing mobile
  tests or extracting common helpers.

Exit criteria:

- A user can approve a pending proposed plan from CLI without opening ACE.
- ACE/mobile/agent-runner all observe the same response and metadata protocol.

### Phase 4: Polish, Integration, and Final Verification

Scope:

- Tighten `-h|--help` for `sase plan`, `sase plan propose`, `sase plan approve`, and `sase plan list`.
- Ensure all public long options have short aliases.
- Update docs, xprompt snippets, default config text, or tests that mention `sase plan <file>` directly.
- Audit for stale examples with `rg "sase plan "`.
- Keep command names/options sorted in help.
- Run formatting and checks.

Tests and commands:

- `just install` if the workspace dependencies may be stale.
- Focused tests added in prior phases.
- `just check` before final handoff because implementation phases change repo files.

Exit criteria:

- No stale `/sase_plan` or docs examples teach `sase plan <file>`.
- CLI help is clear and consistent.
- Full project checks pass.

## Risks and Mitigations

- Approval semantics already differ slightly across ACE and mobile. Mitigate by extracting shared protocol helpers and
  adding tests that pin `approve` versus `tale`.
- Recent approved time is not currently a first-class field. Use `agent_meta.json` mtime initially, but consider writing
  `plan_approved_at` in the shared side-effect helper if that can be done without breaking existing consumers.
- `~/.sase/projects` scans may grow. Prefer existing indexed agent metadata if available; otherwise keep the scan narrow
  to `agent_meta.json` and sort only compact records.
- Generated skill files can drift. Always change `src/sase/xprompts/skills/sase_plan.md`, run
  `sase init-skills --force`, and then `chezmoi apply`.
