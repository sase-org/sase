# Agent Launch UX and Agent Family Types

Status: Research / design memo
Date: 2026-06-04

## Scope

Bryan's inbox asks for two related things:

1. Use **xprompt workflows to define "Agent Family Types"** via xprompt tags.
2. Create a **`/sase_run` xprompt skill** and add a way for users to **approve sase agent
   launches**.

This memo researches the current xprompt model, skill model, daemon launch flow,
Telegram/prompt approval points, and existing family/group metadata, then proposes a
safer and more expressive agent-launch interface. It covers:

- How xprompt tags could define agent family types without creating hidden coupling.
- Whether `/sase_run` belongs as a skill, xprompt, command wrapper, or a combination.
- Where approval should happen for direct `sase run -d`, Telegram, multi-agent xprompts,
  and nested workflow fanout.
- A proposed implementation sequence and risks.

No code is proposed for implementation here; this is design research only.

## Terminology warning: "family" is already overloaded

There is a prior consolidated memo,
`sdd/research/202606/configurable_agent_families_consolidated.md` (2026-06-02), about
making the **plan-chain roles** configurable. That work is about a *vertical lifecycle*:

- `agent_family` = the base name of a plan→code chain (e.g. `myagent`).
- `agent_family_role` = the phase within that chain (`plan`, `code`, `q`, `epic`,
  `legend`, `commit`, `feedback`), keyed off `--`-suffixes in `src/sase/plan_chain.py`.

This memo's "**Agent Family Type**" is a *different, orthogonal* axis: a **horizontal
classification of what kind of work an agent does** (e.g. `refactor`, `reviewer`,
`doc-writer`, `triage`, `spike`), assigned at *launch* by the xprompt that spawned it. A
`refactor`-type launch still goes through the standard plan→code chain, so its coder
member is `type=refactor, role=code`.

Recommendation: do **not** reuse the `agent_family` / `agent_family_role` fields or the
`--` suffix vocabulary for this. Introduce a distinct field (this memo uses
`agent_family_type`) so the two axes never collide. Keeping them separate is the first
defense against the "hidden coupling" the inbox warns about.

## Verified current state

### XPrompt and tag model

- An xprompt is a dataclass `XPrompt` with fields `name`, `content`, `inputs`,
  `source_path`, `tags: frozenset[XPromptTag]`, `snippet`, `description`,
  `skill: bool | list[str] | None`, `local_xprompts`
  (`src/sase/xprompt/models.py:151`).
- `.md` files become a single `prompt_part` workflow; `.yml` files are multi-step
  workflows (`agent`/`bash`/`python`/`prompt_part`/`parallel`, plus `for`/`repeat`/
  `while`/`condition`/`hitl`) — `src/sase/xprompt/workflow_models.py:61,130`.
- Triggered with `#name`, `#name(args)`, `#name:arg`, `#name+`; expanded by
  `process_xprompt_references()` (`src/sase/xprompt/processor.py:268`).
- **Tags are a closed enum.** `XPromptTag` (`src/sase/xprompt/tags.py:12`) is a fixed set:
  `vcs`, `crs`, `fix_hook`, `rollover`, `mentor`, `commit`, `propose`, … Tags are parsed
  by `parse_tags()` and resolved by `get_by_tag()` / `get_by_tag_strict()`
  (`src/sase/xprompt/tags.py:33,74,122`).
- **Tags today drive execution behavior**, not classification: `tags: vcs` makes a
  workflow wrap all others (`wraps_all`), `commit`/`propose`/`mentor` select which
  xprompt runs for a VCS/CRS phase. `get_by_tag_strict()` *requires exactly one* xprompt
  per tag and raises otherwise.
- Multi-agent xprompts split on `---` (`src/sase/xprompt/segment_separators.py:13`);
  fanout also comes from workflow `parallel`/`for`/`repeat` steps.

Takeaway: the existing tag system is a **behavioral router with a uniqueness
assumption**, not a free-form label space. Family *types* are many-xprompts-to-one-type
and must not alter execution — so they should **not** be added to `XPromptTag`.

### Skill model

- A skill is just an xprompt with `skill: true` (or `skill: ["gemini", …]`) in its
  frontmatter, sourced from `src/sase/xprompts/skills/*.md`
  (`src/sase/xprompt/models.py:168`).
- A generation pipeline renders each source per runtime and deploys to
  `~/.claude/skills/<name>/SKILL.md`, `~/.gemini/skills/...`, `~/.codex/skills/...` via
  `run_init_skills()` / `_render_skill_targets()`
  (`src/sase/main/init_skills_handler.py:303,511`), with chezmoi deployment.
- Skills are **guidance documents that teach an agent how/when to call an existing CLI
  command** — e.g. `/sase_plan` documents `sase plan <file>`, `/sase_agents_status`
  documents `sase agents status -j`. They are not executable tools.
- CLI ↔ skill contract must stay in sync (`memory/long/generated_skills.md`): any CLI
  option change requires a matching skill-file and test update.
- There is **no `/sase_run` skill today** (confirmed: `src/sase/xprompts/skills/` has 13
  skills, none for run).

### Launch / daemon flow

- `sase run -d` → `handle_run_special_cases()` strips `-d`, sets daemon mode
  (`src/sase/main/query_handler/special_cases.py:28`) → `run_query_daemon()`
  (`.../query_handler/_daemon.py:8`) → `launch_agent_from_cwd()` →
  `launch_agents_from_cwd()` (`src/sase/agent/launch_cwd.py:99,553`).
- **`launch_agents_from_cwd()` is the canonical chokepoint.** Direct daemon launch,
  multi-prompt fanout, and the Telegram integration all funnel through it
  (`sase-telegram` `_launch_agents_with_notifications()` calls it). Below it sit
  `execute_launch_plan()` (`src/sase/agent/launch_executor.py:48`) and
  `spawn_agent_subprocess()` (`src/sase/agent/launch_spawn.py:94`).
- Multi-prompt `---` auto-routes to daemon and launches N agents sequentially
  (`special_cases.py:50`, `multi_prompt_launcher.py:72`).
- **There is no pre-launch approval anywhere.** The only pre-spawn gate is name-collision
  validation (`launch_validation.py:118`), which only raises for forced name reuse
  outside the TUI. Telegram launches **immediately** on message/caption unless globally
  disabled by `SASE_TELEGRAM_LAUNCH_AGENTS_DISABLED`.

### Existing human-gate / approval infrastructure (all mid-execution)

- Three separate gate protocols exist, all **after** an agent is already running:
  plan approval (`PlanApproval`, `plan_request.json`/`plan_response.json`), user
  questions (`UserQuestion`, `question_*.json`), and workflow HITL (`HITL`,
  `hitl_*.json`). Each kills the runner's process group and polls a response file
  (`plan_command_handler.py:15`, `run_agent_helpers_questions.py:22`).
- All three are surfaced through one notification system whose Rust wire is already a
  generic envelope: `NotificationWire { action, action_data, … }`
  (`../sase-core/.../notifications/wire.rs`). Adding a new gate kind costs nothing at the
  wire layer — only the sender payload + modal renderer change.
- TUI renders them via modals (`plan_approval_modal.py:115`,
  `approve_options_modal.py:93`); Telegram mirrors them via outbound notifications +
  inline buttons + a two-step feedback flow + a persistent `pending_actions.json`
  (`sase-telegram` `formatting.py:329`, `inbound.py:281`, `pending_actions.py:38`).
  Telegram's `_ACTIONABLE_ACTIONS = {"PlanApproval", "HITL", "UserQuestion"}`.
- Auto-approve precedence already exists for unattended flows:
  `SASE_AGENT_AUTO_APPROVE_PLAN_ACTION` → `SASE_AGENT_AUTO_PLAN_ACTION` →
  `agent_meta.auto_approve_plan_action` → `SASE_AGENT_AUTO_APPROVE`/`agent_meta.approve`
  (`plan_approve_handler.py:43`). Any new gate must honor an analogous precedence or it
  will deadlock CI.

### Existing agent metadata / grouping

- `agent_meta.json` (wire: `core/agent_scan_wire_markers.py:84`) already carries
  `agent_family`, `agent_family_role`, `plan_chain_root`, `role_suffix`, `workflow_name`,
  and a single user-managed `tag` (persisted separately in `~/.sase/agent_tags.json`,
  regex `^[A-Za-z0-9_.-]+$`).
- The TUI Agents tab groups by project → ChangeSpec → name-root → name-prefix, with
  `GroupingMode` STANDARD/BY_DATE/BY_STATUS (`ace/tui/models/agent_groups/`). Family base
  is derived in `_grouping_name()`. The single `tag` already drives grouping/side-panel
  splits — a natural rendering hook for a richer family-type field.

## Design

### 1. xprompt tags → agent family types, without hidden coupling

The "hidden coupling" trap is real because the existing `XPromptTag` enum is a behavior
router with a uniqueness contract. If family types are stuffed into it:

- `get_by_tag_strict()` breaks (many xprompts share a type).
- A type silently inherits `vcs`/`commit`/`wraps_all` execution semantics.
- Classification and routing become entangled — exactly what to avoid.

Proposal: **declare family types in a separate, open namespace that is metadata-only.**

- Add an optional `family_type:` field to xprompt frontmatter and workflow YAML (a free
  string, validated against `^[A-Za-z0-9_.-]+$`, the same charset as `tag`). It is
  *parsed alongside* `tags` but stored as its own field on `XPrompt`/`Workflow`, **not**
  added to the `XPromptTag` enum.
- Alternatively (if a tag-shaped surface is desired) reserve a **prefixed tag namespace**
  `type/<name>` that the loader peels off into the same `family_type` field before
  `XPromptTag` parsing. Either way the value lands in a dedicated field, never in the
  behavioral enum.
- The launcher propagates the spawning xprompt's `family_type` into a new
  `agent_family_type` field in `agent_meta.json`, mirrored in the `sase-core` scanner
  wire next to the existing family fields (this is a cross-frontend contract, like
  `agent_family` already is — the prior memo established that precedent).
- **Consumers read it explicitly and only for non-execution concerns:** TUI grouping/
  filtering, the launch-approval policy (below), status/telemetry. It must **never**
  change the prompt, model, runtime, or routing. If a user wants a type to imply a model
  or prompt, that belongs in the xprompt body/directives, not implied by the type.

Why this avoids hidden coupling: the type is a *declared label that travels with the
agent*, and every behavior that keys off it does so by reading an explicit field with a
documented contract. Nothing about expansion or execution silently forks on it.

Relationship to the prior plan-chain work: `agent_family_type` is orthogonal to
`agent_family_role`. A launch tagged `family_type: refactor` produces a chain whose
members are all `type=refactor` while their `role` cycles `plan`→`code`→…. If/when the
configurable-families schema from the prior memo lands, a family *type* could optionally
name which *role state machine* to use — but that is an opt-in pointer, not an implicit
coupling.

### 2. Where `/sase_run` belongs: skill + thin CLI, not a pure xprompt

The three candidate forms map cleanly onto what each layer can do:

- **Pure xprompt (`#sase_run`)** — expands to prompt *text*. Launching is a side-effecting
  CLI action, so a pure xprompt cannot launch. Rejected as the primary form. (xprompt
  tags still *declare* family types — that is their role here.)
- **Command wrapper** — `sase run` already exists. We need only additive flags, not a new
  command surface.
- **Skill** — the SASE-native way to teach an agent *when and how* to invoke a CLI
  command, deployed uniformly across runtimes by the generated-skills pipeline.

Recommendation: a **combination, anchored on a skill backed by the existing CLI.**

- Add `src/sase/xprompts/skills/sase_run.md` with `skill: true`. It documents: how an
  agent launches sub-agents with `sase run -d`, how to choose a `--family-type`, how
  multi-agent `---` fanout works, and — critically — that launches may require approval
  and how to interpret a deferred/queued launch. Generated per runtime; kept in sync with
  CLI options per the `generated_skills.md` contract; uniform across Claude/Gemini/Codex.
- Add CLI flags on `sase run` (each with long+short per the short-options gotcha):
  `-F/--family-type <name>` and an approval-policy flag (e.g.
  `-A/--approval auto|ask|inherit`). These are the consumption side.
- Declaration stays in xprompts: a `#refactor_sweep` workflow tagged
  `family_type: refactor` is the *definition* of a family type; `/sase_run` + `sase run
  -F refactor` is the *invocation*. Clean separation of declare vs invoke.

So: **xprompt tags define family types; the `/sase_run` skill and CLI flags consume
them.** `/sase_run` is a skill (+ minimal CLI), explicitly not a pure xprompt.

### 3. Where approval should happen

Put **one pre-launch gate at the `launch_agents_from_cwd()` chokepoint**, because all four
surfaces funnel through it. Gating per-surface would leave bypass paths; gating below it
(at `spawn_agent_subprocess`) is too late to present a coherent batch. The gate consults
an **approval policy** resolved from: the resolved `family_type`, the launch *surface*,
the fanout count, and the existing auto-approve precedence.

Per surface:

- **Direct `sase run -d` (terminal).** A human is at the keyboard, so default to
  permissive (preserve today's immediate-launch behavior — backward compatibility), with
  an opt-in synchronous TTY confirmation when policy says `ask` or when the family type is
  marked approval-required. Never block a non-interactive/CI invocation that has
  auto-approve set.
- **Telegram (remote, async).** This is where pre-launch approval matters most — the user
  is not at a terminal and today launches fire instantly. Insert a `LaunchApproval` gate
  **before** spawn, reusing the proven plan-approval machinery: a `launch_request.json` /
  poll `launch_response.json` pair, a new notification `action="LaunchApproval"` on the
  generic wire, Telegram inline buttons (approve / reject / edit-prompt), and
  `pending_actions.json` (which already has 24h stale cleanup — a natural TTL for queued
  launches). Add `"LaunchApproval"` to Telegram's `_ACTIONABLE_ACTIONS`.
- **Multi-agent xprompts (`---` → N agents).** Approve at the **batch** level before *any*
  segment spawns: one notification summarizing N segments with approve-all / reject /
  per-segment options. This must reconcile with the existing partial-launch failure path
  (`_MultiPromptPartialLaunchError`): approval is decided before spawning begins, so a
  later spawn failure is still a partial-launch, not a partial-approval.
- **Nested workflow fanout (`parallel`/`for`/`repeat` spawning agents).** These fire deep
  in execution, often unattended — interactive approval per spawn is infeasible. Use a
  **budget/quota** instead: a family type (or the parent launch) declares `max_fanout`,
  and the parent's approval carries a budget that nested spawns draw down. Within budget →
  auto-proceed; over budget → emit one `LaunchApproval` notification for the overflow
  rather than blocking each child. Always honor the auto-approve precedence so batch/CI
  workflows never deadlock.

The unifying idea: **lift approval from mid-execution (plan/question/HITL) to pre-launch**,
reusing all the existing gate infrastructure (generic notification wire, request/response
files, TUI modal, Telegram buttons, pending-actions, auto-approve precedence) at the spawn
chokepoint. The policy — not the call site — decides synchronous-confirm vs
notification-and-queue vs budget-draw vs auto-pass.

### 4. Proposed implementation sequence

- **Phase 0 — Disambiguate terminology.** Reserve `agent_family_type` (distinct from
  plan-chain `agent_family`/`agent_family_role`). Document the two axes. No code behavior
  change.
- **Phase 1 — Declare + propagate family types (metadata only).** Add `family_type:` to
  xprompt/workflow frontmatter as its own field (not in `XPromptTag`). Propagate into
  `agent_meta.json` and the `sase-core` scanner wire. Surface it in TUI grouping/filter.
  No execution or approval change yet — purely classification. Tests: a tagged xprompt
  yields the expected `agent_family_type` on launched agents; untagged is unchanged.
- **Phase 2 — `/sase_run` skill + CLI flags.** Add `sase run -F/--family-type` and
  `-A/--approval`. Author `sase_run.md` (`skill: true`); regenerate skills; keep CLI↔skill
  docs and tests in sync per `generated_skills.md`. Approval flag is accepted but
  defaults to today's behavior until Phase 3.
- **Phase 3 — Pre-launch gate at the chokepoint.** Add approval-policy resolution +
  `LaunchApproval` notification + `launch_request.json`/`launch_response.json` in
  `launch_agents_from_cwd()`. Wire the auto-approve precedence first so CI/batch never
  regress. Terminal path: synchronous TTY confirm for `ask`. Default policy permissive for
  direct terminal launch.
- **Phase 4 — Remote + TUI launch-approval UI.** Reuse `pending_actions`, callbacks, and a
  TUI modal. Telegram buttons: approve / reject / edit-prompt. Add `LaunchApproval` to
  `_ACTIONABLE_ACTIONS`.
- **Phase 5 — Fanout governance.** Batch-level approval for multi-agent `---` launches;
  per-family-type `max_fanout`; budget inheritance for nested workflow spawns.
- **Phase 6 (optional) — Move policy to `sase-core`.** Mirror family-type classification
  and approval-policy resolution into the Rust core so every frontend agrees, leaving
  Python to host markers, subprocesses, modals, and side effects — the same boundary the
  prior families memo recommends.

### Risks

- **Terminology collision.** "Family" already means the plan-chain. Mitigate with the
  distinct `agent_family_type` field and explicit docs; never overload `agent_family`.
- **Tag-enum coupling.** Adding types to `XPromptTag` would entangle classification with
  `vcs`/`commit`/`wraps_all` routing and break `get_by_tag_strict()`'s uniqueness
  assumption. Mitigate by keeping `family_type` a separate metadata field.
- **Silent behavioral coupling.** If a family type ever implies a model/prompt/runtime,
  the "hidden coupling" the inbox warns about returns. Keep types metadata-and-policy
  only; require explicit declaration for any behavior.
- **CI / unattended deadlock.** A pre-launch gate that ignores the existing auto-approve
  precedence would hang batch flows. Wire that precedence in Phase 3 *before* enabling any
  blocking behavior; default nested-within-budget to open.
- **Chokepoint bypass.** The gate only works if every surface routes through
  `launch_agents_from_cwd()`. Audit for any path that reaches `spawn_agent_subprocess()`
  directly; gate must sit above the spawn, not beside each caller.
- **Backward compatibility.** Existing `sase run -d` users expect instant launch. Keep the
  terminal default permissive; make stricter policy opt-in (per family type or config).
- **Remote latency / stale launches.** Queued Telegram approvals need a TTL — reuse
  `pending_actions.json`'s 24h cleanup; decide whether expiry means drop or auto-reject.
- **Multi-agent partial launches.** Batch approval must be atomic w.r.t. the decision but
  tolerate later per-segment spawn failures (`_MultiPromptPartialLaunchError`); don't
  conflate "approved" with "all spawned".
- **Fanout amplification.** Nested `parallel`/`repeat` can multiply spawns fast; without a
  budget a single approval could authorize an unbounded tree. `max_fanout` + budget draw
  is a hard requirement for Phase 5, and any silent cap must be logged, not hidden.

## Recommendation

1. Introduce **`agent_family_type`** as a metadata-only classification declared by a new
   `family_type:` xprompt/workflow field (a separate namespace, never the `XPromptTag`
   enum), propagated to `agent_meta.json` and the `sase-core` wire, consumed only for
   grouping/policy/telemetry. This keeps types expressive without hidden coupling.
2. Ship **`/sase_run` as a generated skill plus thin `sase run` flags** (`-F/--family-type`,
   `-A/--approval`). xprompt tags *declare* family types; the skill/CLI *invoke* them.
3. Add **one pre-launch approval gate at the `launch_agents_from_cwd()` chokepoint**,
   reusing the existing notification wire, request/response files, TUI modal, Telegram
   buttons, pending-actions, and auto-approve precedence. Resolve behavior by policy:
   synchronous confirm for terminal, notify-and-queue for Telegram, batch approval for
   multi-agent `---`, and budget draw for nested workflow fanout.
4. Sequence it metadata-first (Phases 0–2), then the gate (Phase 3), then remote/TUI UI and
   fanout governance (Phases 4–5), optionally moving pure policy into `sase-core` (Phase 6).

This is intentionally compatible with the prior `configurable_agent_families_consolidated.md`
work: that memo makes the *vertical* plan-chain roles configurable; this memo adds an
orthogonal *horizontal* type axis and lifts approval to launch time. They share the
`sase-core` boundary and the generic notification wire, and can land independently.
