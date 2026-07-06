---
create_time: 2026-07-05
updated_time: 2026-07-05
status: research
---

# Dynamic Agent Families: v1 High-Level Design and v2 Direction

## Scope

Follow-up to `sdd/research/202607/dynamic_agent_families_note_critique.md`
(2026-07-05). That doc asked thirteen open questions; Bryan answered five of
them as PDF comments (`~/bob/ref/chat/dynamic_agent_families_note_critique.md`).
This doc incorporates those answers and delivers:

1. A very high-level design for **v1** (what to build, in what order, and the
   small set of decisions still needed).
2. A recommended direction for **v2**, with critiques of the v2 idea itself and
   the open questions that must be answered before v2 design work starts.

New code exploration for this doc: the full plan-approval protocol (modal, CLI,
response writer, runner dispatch, auto modes) — because Bryan's comments make
approval-time family-member insertion the v2 centerpiece.

## Decisions Locked In (from Bryan's comments on the critique)

1. **Running parents are in scope for v1.** `%n` MAY target a still-running
   `foo`. This pulls queued/waiting child rows into v1.
2. **Role-derived statuses win.** The `run_status=`/`done_status=` kwargs are
   dropped; `%n(foo, code)` gets the existing code-phase statuses. No custom
   status strings in v1.
3. **All three user stories are valid motivations**: manual feedback/Q&A rounds
   on finished agents, arbitrary named members (reviewer, tester), and
   agent-initiated member spawning. Additionally, the long-term north star:
   **plan-approval options that run custom family members at select lifecycle
   points** — e.g. approve a plan with a flag that runs an `improve_plan` agent
   after the `plan` agent, and/or a `tester` agent after the `code` agent.
4. **`%!` is dead, and so are root bash/python rows.** Neither is in any
   version of this project.
5. **TUI root/child normalization is a v1 prerequisite** (consequence of
   decision 1: queued children must render as child rows).

The scope split that falls out of these decisions:

- **v1 — user-initiated family extension**: `%n(parent, suffix)` from any
  launch surface the user already types prompts into, queued children under
  running parents, prompt-assembly xprompts, TUI normalization.
- **v2 — lifecycle-initiated family extension**: approval-gate options that
  insert custom members at chain points, plus agent-initiated spawning behind
  `LaunchApproval`. This is the family state-machine territory of the
  2026-06-17 memo.

## v1 High-Level Design

One sentence: *a user can manually attach a new member to an existing agent's
`--` family by writing `%n(parent, suffix)` in an ordinary `sase run` prompt;
if the parent is still running, the member queues as a waiting child row under
the parent and starts when the parent finishes.*

### Component A — `%n(parent, suffix)` directive extension

Extend the existing single-value `%name`/`%n` directive
(`src/sase/xprompt/_directive_types.py`, `src/sase/xprompt/directives.py`):

- **Forms.** `%n(name)` keeps today's meaning (plain agent naming).
  `%n(parent, suffix)` means family attach. `%n(parent, @)` auto-allocates the
  next numeric suffix using the same template semantics as
  `allocate_agent_family_child_suffix` (`src/sase/plan_chain.py:419`).
- **Strict validation.** Reject >2 positionals and *all* keyword args loudly
  (today both are silently dropped — `directives.py:359-380`). This is the
  whole backward-compat surface and closes the silent-typo hazard.
- **Suffix → role mapping.** Reserved suffixes (`plan`, `q`, `code`, `epic`,
  `legend`, `commit`, per `plan_chain.py:10-56`) select the corresponding
  built-in role and its statuses. `@`/numeric suffixes are feedback/Q&A-round
  members. Custom words (e.g. `reviewer`, `tester`) are allowed with a generic
  role: standard `RUNNING`/`DONE` statuses, `agent_family_role` recorded as the
  custom word so the future v2 evaluator can interpret it without migration.
  Legacy `.`/`-` spellings are rejected in `%n` (canonical `--` only).
- **Collision policy.** If `parent--suffix` already exists, fail loudly and
  suggest `@` (do not silently auto-number a named suffix).
- **Metadata.** Written via the existing `plan_chain.py` helpers: same
  `agent_family`, `agent_family_role`, `role_suffix`, `plan_chain_root` fields
  the runner handoff writes. No parallel lineage scheme — this is the
  compatibility contract with v2.
- **Statuses.** Role-derived only (decision 2). No new status strings, no
  changes to `status_buckets.py` closed sets.

### Component B — parent resolution and the visibility helper

- **Resolution rule.** Resolve `parent` to the newest matching undismissed
  root agent in the current project's scan scope (backed by the artifact index
  queries in `src/sase/core/agent_scan_facade.py`). Error on absent or
  ambiguous; dismissed → hard fail with an error naming the revive path.
- **A name-keyed "exists and undismissed" helper is new code.** Dismissal is
  keyed by `(AgentType, cl_name, raw_suffix)` in
  `~/.sase/dismissed_agents.json` (`src/sase/ace/dismissed_agents.py`); the
  helper maps a name to that identity and checks membership + panel
  visibility. Put the pure classification behind the Rust facade (rust-core
  litmus test: mobile/web would need the identical check).
- **Check at preparation time, not just parse time.** The constraint check
  runs inside launch preparation (the Rust `prepare_agent_launch` seam in
  `src/sase/core/agent_launch_facade.py`) so the dismiss-between-check-and-
  spawn race is narrowed, and the failure surfaces on the launching surface
  (CLI stderr, TUI toast, Telegram reply).
- **Parent state.** Running or terminal are both fine (decision 1); only
  dismissed/absent/ambiguous fail.

### Component C — queued/waiting children under running parents

New in v1 per decision 1. Reuse the existing wait machinery rather than
inventing a queue:

- When the resolved parent is still running, the child launches immediately
  but enters the existing wait barrier: the runner writes `waiting.json` and
  blocks on dependency resolution (`src/sase/axe/run_agent_wait.py`,
  `src/sase/core/wait_dependency_resolution.py`) — effectively an implicit
  `%wait(for=<parent>)`.
- **Gap to close:** the current dependency-resolution predicate treats only
  `Done` as resolved (`agent_completion.py`), but family parents terminate in
  `PLAN DONE`, `TALE DONE`, `EPIC CREATED`, `FAILED`, `STOPPED`, etc. The
  predicate needs family-aware terminal detection (reuse the terminal set in
  `src/sase/agent/status_buckets.py`).
- **Parent-failure policy (v1 decision needed, see below):** what a queued
  child does when the parent ends in `FAILED`/`STOPPED`.

### Component D — TUI root/child normalization (build first)

A v1 prerequisite per decision 5, and the right first bead because C renders
through it:

- Unify the two disjoint child-attachment mechanisms — workflow step children
  via `parent_workflow` + `step_type` vs follow-up agent children via
  `parent_timestamp` only (`src/sase/ace/tui/models/agent.py:116-138,528-530`,
  `_agent_status_apply.py:269-274`) — into one child-linkage model.
- Add pre-launch **WAITING child rows**: a queued `%n` child renders under its
  running parent with `WAITING` status (today `WAITING` is a root-only state).
- **Scope cut (decision 4):** "python/bash as root rows" is dropped from the
  normalization entirely; bash/python remain workflow children only.
- Constraints: no added synchronous I/O in loaders (read `memory/tui_perf.md`
  first); new linkage/marker fields ride the Rust scan wire, so `sase-core`
  changes are in scope for this bead.

### Component E — `#with_feedback` and `#with_q_and_a` xprompts

Pure prompt assembly; the directive launches, the xprompt only builds the
body (per the 2026-06-18 `#with_q_and_a` memo):

- `#with_q_and_a` per the existing memo: hidden python step calling a shared
  `assemble_question_followup_prompt()` helper, `qa_file` contract, byte-parity
  tests against `handle_questions_marker`.
- `#with_feedback` needs the same treatment first: extract the feedback-replan
  prompt assembly (the "### Additional Requirements" accumulated-bullets
  construction in `src/sase/axe/run_agent_exec_plan.py:169-238`) into a public
  helper, then wrap it as an embeddable xprompt with parity tests.
- Composed v1 usage: `%n(foo, @) #with_feedback:: <feedback text>`.

### v1 build order

1. **D** — TUI normalization + waiting child rows (own bead; `sase-core` wire
   planning; `tui_perf.md` review). Unblocks C's rendering.
2. **E** — extract the two prompt-assembly helpers and ship both xprompts.
   Independently useful even before `%n` lands.
3. **A + B** — `%n(parent, suffix)` with strict validation, for terminal
   parents first (resolution helper, metadata, role-derived statuses, loud
   failures per surface).
4. **C** — enable running parents / queued children on top of D.

### v1 non-goals

`%!` and any inline-shell xprompt support; root bash/python rows; custom
status strings; agent-initiated `%n` (v2, needs `LaunchApproval`);
approval-option member insertion (v2); generic family YAML (v2).

### v1 decisions still needed (small set)

1. **Custom-suffix policy.** Recommendation above is "open set with generic
   role"; the conservative alternative is reserved + `@` only in v1. Pick one.
2. **Parent-failure policy for queued children.** Options: (a) run anyway,
   (b) cancel to `STOPPED` with a notification, (c) stay waiting for a manual
   decision. Recommend (b) — it is the least surprising and cheapest; (c) is
   v2 gate territory.
3. **Inheritance contract.** Recommend: project and workspace ref inherit from
   the parent; model/effort come from the launch site (normal directive
   resolution); no chat inheritance unless the user writes `#fork:<parent>`
   explicitly; `SASE_PLAN` only for `code`-role members whose parent family
   has a committed/archived plan (mirroring the handoff rules in
   `run_agent_exec_plan_accept.py`).
4. **Remote surfaces in v1.** Recommend: `%n` is honored from Telegram/mobile
   exactly like any other user-typed `sase run` prompt (it is user-initiated,
   so it does not need `LaunchApproval`), with constraints checked at prep
   time and failures replied on-surface.

## v2 Recommended Direction

North star (Bryan's comment): *users can approve a plan with custom options
that insert custom family members at select points in the family lifecycle* —
`improve_plan` after `plan`, `tester` after `code` — plus agent-initiated
member spawning.

### What v2 lands on today (verified this session)

- **Plan approval is a three-surface protocol.** TUI `PlanApprovalModal`
  (keys: `a` approve, `t` tale, `c` custom via `ApproveOptionsModal` with
  model/prompt overrides, `r` reject, `f` feedback, `e` edit, `E` epic, `L`
  legend — `src/sase/ace/tui/modals/plan_approval_modal.py:120-137`), CLI
  `sase plan approve --kind {approve,commit,epic,legend,tale}`
  (`src/sase/main/parser_plan.py:56-83`), and the shared response writer
  `execute_plan_approval_response` / `_plan_response_json`
  (`src/sase/plan_approval_actions.py:43,97`). The runner blocks polling
  `plan_response.json` (`src/sase/llm_provider/_plan_utils.py:196-318`).
- **The choice vocabulary is hard-coded in four places**: the modal protocol
  dict (`plan_approval_modal.py:27-50`), the `ApproveOptionsModal` tables, the
  response writer (`plan_approval_actions.py:97-154`), and the CLI `--kind`
  choices (`parser_plan.py:65`). Any new option today means editing all four.
- **The next-role transition is one hard-coded seam.** `handle_accepted_plan`
  (`src/sase/axe/run_agent_exec_plan_accept.py:222`) branches `if/else` on the
  action and spawns exactly one follow-up (coder at `:438-531`, epic/legend at
  `:350-437`, commit-only returns terminal at `:331`). **After the coder there
  is no seam at all** — the runner returns with no further chaining — so
  "`tester` after `code`" requires a new lifecycle event, not just a config
  knob.
- **No hook mechanism exists between approval and code launch** (confirms the
  note's crossed-out "plan-proposed hooks" item was describing something that
  never existed). The only post-coder execution is reconstructed embedded VCS
  refs (`#propose`/`#commit` post-steps, `run_agent_exec_plan_accept.py:340`),
  which are workflow-step hooks, not family insertion points.
- **`%auto` modes bypass the gate entirely.** `get_auto_plan_approval_action`
  (`src/sase/main/plan_approve_handler.py:59-77`) short-circuits before the
  notification/response round-trip. Custom inserted members must define their
  auto-mode behavior or they silently never run in `%auto:tale`-style flows.
- **Frontend contracts are closed.** Pending-action kinds and mobile action
  enums in `sase-core` recognize `PlanApproval`/`HITL`/`UserQuestion` only;
  new choices/roles cross the Rust wire.

### Recommended v2 shape (staged)

Adopt the 2026-06-17 memo's family state-machine architecture, sequenced so
each stage is independently shippable and the approval-options feature falls
out of stages 2+4+5 rather than being bolted on:

1. **Golden-equivalence harness** for current plan/question flows (approve,
   run, tale, commit-only, epic, legend, feedback replan, questions in every
   phase, auto modes, killed runs). This is the memo's step 1 and is what
   makes every later stage safe.
2. **Collapse the four hard-coded choice tables into one data-driven choice
   registry** — single source of truth consumed by the modal, the
   `ApproveOptionsModal`, the CLI parser, and the response writer. No behavior
   change; pure de-duplication. This is the cheapest prerequisite for custom
   options and is worth doing even if v2 stalls.
3. **Built-in `standard_plan_chain` family definition + evaluator**, routing
   the existing markers through typed events (`plan_submitted`,
   `questions_submitted`) with parity proven against the harness. Add a
   `role_completed` event at follow-up finalize — this is the missing "after
   code" seam.
4. **Custom roles as data.** `improve_plan` = a role with a prompt template
   and placement `after: plan`; `tester` = a role `after: code` hooked on
   `role_completed`. Prompt templates are xprompt references; role suffixes
   validate against the reserved set. v1's `%n` metadata is already evaluator-
   compatible (Component A), so manually-attached and gate-inserted members
   look the same to the TUI.
5. **Approval-choice extensions as gate choices.** Custom options surface
   through the *existing* `PlanApproval` renderer with data-driven choices
   (compatibility protocol per the memo) — e.g. a checkbox/flag section in
   `ApproveOptionsModal` ("also run: improve_plan, tester") rather than new
   top-level keys. A generic decision renderer comes only after parity.
6. **Agent-initiated spawning** per the 2026-06-04 memo: `/sase_run` generated
   skill + host-side launch-request command, `LaunchApproval` pending action,
   preview object shared by CLI/TUI/Telegram/mobile. Agent-written `%n` routes
   through this gate; family-internal spawns can use bounded delegated tokens.
7. **Semantic-status + display-label split** (needs `sase-core` wire
   versioning) so custom roles can get custom labels without breaking the
   closed status sets — this is where the dropped v1 kwargs eventually return,
   as display labels only.

### Critiques of the v2 idea (what to watch)

1. **"After code" is much bigger than "after plan."** Post-plan insertion can
   piggyback on the existing approval gate; post-code insertion needs the new
   `role_completed` event, a decision about whether tester output gets its own
   gate, and a composition rule with the embedded VCS refs that currently run
   after the coder (does `tester` run before or after `#propose`?). Budget
   these separately; do not let "after plan" wait for "after code."
2. **Option explosion in the approval UX.** The modal is single-letter
   keybindings and Telegram is buttons; N custom options do not scale as
   top-level choices. Fold custom members into the existing `c`(ustom) path /
   `ApproveOptionsModal` as toggles, and consider per-project sticky defaults,
   or the feature will be unusable from mobile.
3. **Auto-mode silently skips gates.** Whatever policy is chosen
   (inserted members always run vs. only on interactive approval), it must be
   explicit in the family definition, or `%auto:tale` users will file bugs
   about testers that never ran.
4. **Loop risk.** `improve_plan` after `plan` implies the improved plan may
   re-enter review; feedback rounds already loop. Without max-visit counters
   per role (the June 17 memo's loop guidance), a family can cycle forever.
5. **Failure semantics are the real design work.** "Insert tester after code"
   is easy to say; what happens when the tester *fails* (block commit? notify
   and continue? rerun?) is gate semantics, and pretending it is just
   sequencing will produce a half-feature. Decide failure→transition mapping
   per inserted role.
6. **It is not Python-local.** Every new choice, role, pending-action state,
   and status label crosses the `sase-core` wire (mobile action details,
   scan fields, pending actions). Version the wire; keep old clients safe.
7. **Interim-shortcut temptation.** A quick "post-approval insertion list"
   config could ship without the evaluator — but it would be a second,
   parallel family mechanism that v2 proper would then have to absorb. The
   floor for any interim is stage 2 (the choice registry); below that,
   decline the shortcut.

### v2 open questions (answer before v2 design starts)

1. **Definition surface.** Where do custom member/option definitions live —
   file-backed `agent_family` YAML (memo recommendation), plan-approval
   config, or xprompt front matter? Note config-defined workflow blocks are
   deliberately ignored by both Python and Rust catalogs today, so config-only
   definitions need explicit new support.
2. **Approval UX.** Extend `ApproveOptionsModal` with member toggles, add
   per-project defaults, or both? What do Telegram/mobile render for the same
   choices?
3. **Re-review policy.** Does `improve_plan`'s output re-enter the plan
   approval gate, auto-continue to code, or make that configurable per role?
   What is the loop cap?
4. **The "after code" event.** Is `role_completed` emitted from runner
   finalize, from status transition, or from the family evaluator — and does
   it fire for epic/legend branches too?
5. **VCS-ref composition.** Where do inserted post-code members sit relative
   to the reconstructed `#propose`/`#commit` embedded refs?
6. **Auto-mode policy.** Do inserted members run under
   `%auto`/`auto_approve_plan_action`, and is that per-member or per-family?
7. **Agent-initiated `%n`.** Always a fresh `LaunchApproval`, or can a family
   definition grant a bounded delegated budget (max members, max depth,
   expiry) for its own internal spawns?
8. **Label/semantic status split.** Is it required for the first custom roles
   (probably — `improve_plan` deserves a better label than `RUNNING`), and
   what is the wire-versioning story?
9. **v1→v2 compatibility test.** Concretely: a v1 `%n(foo, reviewer)` member
   must classify, group, and status correctly under the v2 evaluator with no
   metadata migration. Make this an explicit parity test, not an assumption.
10. **Sequencing.** Does v2 wait for the public-launch-readiness work in
    flight (202607 blog audit), and does stage 6 (agent-initiated spawning)
    ship before or after stages 3-5 (evaluator + custom roles)? Recommendation:
    stages 1-2 can start anytime (pure refactor + harness); 3-5 before 6.

## Key References

- Decisions: `~/bob/ref/chat/dynamic_agent_families_note_critique.md` (Bryan's
  comments); the note `~/bob/sase_dyn_agent_fam.md`.
- Prior research: `sdd/research/202607/dynamic_agent_families_note_critique.md`,
  `sdd/research/202606/dynamic_agent_families_xprompt_workflows_consolidated.md`
  (family state machine), `sdd/research/202606/agent_launch_ux_family_types_consolidated.md`
  (`LaunchApproval`, `/sase_run`),
  `sdd/research/202606/with_q_and_a_xprompt_consolidated.md`.
- Approval protocol: `src/sase/ace/tui/modals/plan_approval_modal.py`,
  `src/sase/ace/tui/modals/approve_options_modal.py`,
  `src/sase/plan_approval_actions.py`, `src/sase/main/parser_plan.py`,
  `src/sase/main/plan_approve_handler.py`,
  `src/sase/llm_provider/_plan_utils.py`.
- Runner seams: `src/sase/axe/run_agent_exec_plan.py`,
  `src/sase/axe/run_agent_exec_plan_accept.py` (the only next-role seam),
  `src/sase/axe/run_agent_exec_questions.py`.
- Families/directives: `src/sase/plan_chain.py`,
  `src/sase/xprompt/_directive_types.py`, `src/sase/xprompt/directives.py`.
- Waiting/dismissal: `src/sase/axe/run_agent_wait.py`,
  `src/sase/core/wait_dependency_resolution.py`,
  `src/sase/ace/dismissed_agents.py`.
- TUI rows: `src/sase/ace/tui/models/agent.py`,
  `src/sase/ace/tui/models/_agent_status_apply.py`,
  `src/sase/agent/status_buckets.py`; perf rules `memory/tui_perf.md`.
