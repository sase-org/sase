---
create_time: 2026-07-06
updated_time: 2026-07-06
status: research
---

# Dynamic Agent Families: User-Manual Research (Design + Usage)

> **Status update (2026-07-06):** the user guide this research supports has shipped as `docs/agent_families.md`
> (commit `2b4d8e9ae`, wired into the mkdocs nav), with companion updates to `docs/cli.md`, `docs/configuration.md`,
> and `docs/ace.md` covering every gap listed in §5. A follow-up verification pass (`9a784e2ca`) corrected two claims
> that also appear below — prefer the shipped doc on these points:
>
> 1. **§3.4 "v1 interop" overstates parity.** A manual `%n(foo, <custom_role>)` attach shares family metadata,
>    grouping, and dismissal with an evaluator-inserted member, but it runs outside the runner loop: it never emits
>    `role_completed` and never gets an `agent_family_custom_role` snapshot, so it shows generic RUNNING/DONE labels
>    even when the suffix matches a defined role.
> 2. **`on_done` has no runtime consumer.** It is validated and recorded in the role snapshot only; the
>    `improve_plan`-style re-review loop is driven by the role's prompt template resubmitting a plan, with the
>    evaluator enforcing `max_visits`.

## Scope

Research to support writing a user manual for the **dynamic agent families** feature, implemented across two closed
epics:

- **`sase-5f` — Dynamic Agent Families v1** (5 phases): user-initiated family extension via `%n(parent, suffix)`,
  queued children under running parents, the `#with_feedback` / `#with_q_and_a` prompt-assembly xprompts, and TUI
  child-row normalization. Commits: `9caeb0d37` (5f.1), `41b27fbaa` (5f.2), `7b357a097` (5f.3), `dfd9f50f0` (5f.4),
  `a660d9227` (5f.5), `c5f18ae90` (edge cases).
- **`sase-5g` — Dynamic Agent Families v2** (9 phases): lifecycle-initiated family extension — the plan-approval choice
  registry, typed handoff events + the `standard_plan_chain` evaluator, the `role_completed` after-code seam,
  `kind: agent_family` YAML custom roles, approval-gate member toggles with sticky defaults, the `LaunchApproval`
  pending action + `/sase_run` generated skill, and custom-role display labels. Commits: `1466dbf77` (5g.1),
  `5f390345a` (5g.2), `bfe4cc298` (5g.3), `19e780dd5` (5g.4), `72fc527b2` (5g.5), `b762964a5` (5g.6), `19a07856d`
  (5g.7), `deaf571e0` (5g.8), `5eb450842` (5g.9); refactors `0ea37bfa5`, `179a0398a`; closeout `f00d67d6a`.

Design lineage (read for rationale, superseded on specifics by the code anchors below):
`sdd/research/202607/dynamic_agent_families_v1_v2_design.md` (the v1/v2 design),
`sdd/research/202607/dynamic_agent_families_note_critique.md` (critique of the original `~/bob/sase_dyn_agent_fam.md`
note), `sdd/research/202606/dynamic_agent_families_xprompt_workflows_consolidated.md` (family state-machine
architecture), `sdd/research/202606/agent_launch_ux_family_types_consolidated.md` (`LaunchApproval`, `/sase_run`),
`sdd/research/202606/with_q_and_a_xprompt_consolidated.md`. Epic plans: `sdd/epics/202607/dynamic_agent_families_v1.md`
and `..._v2.md`.

All behavior below was verified against the current tree (post-`f00d67d6a`); line anchors will drift.

## 1. Concept Overview

A **plan-chain agent family** is the group of agents sharing a `--`-separated base name: `foo`, `foo--plan`,
`foo--code`, `foo--plan-2`, ... Before this project, families grew only from the inside: the runner's marker-driven
handoff (plan approved → spawn coder, questions answered → spawn follow-up) was the sole mechanism that could attach a
new member, along hard-coded transitions.

**Dynamic agent families** turn family extension into a first-class primitive, in two halves:

- **v1 — user-initiated extension.** A user attaches a new member to any existing family by writing
  `%n(parent, suffix)` in an ordinary prompt, from any launch surface (CLI, TUI, Telegram/mobile). If the parent is
  still running, the member queues as a WAITING child row and starts when the parent finishes. Two bundled xprompts
  (`#with_feedback`, `#with_q_and_a`) assemble the classic follow-up prompt bodies; the directive launches, the
  xprompts only build text.
- **v2 — lifecycle-initiated extension.** The plan/questions handoff now routes through typed events and a family
  **evaluator** executing a family *definition*. Users define custom roles declaratively in `kind: agent_family` YAML
  (e.g. `improve_plan` after `plan`, `tester` after `code`), toggle them per approval at the plan gate (TUI toggles or
  `sase plan approve --with/--without`), and set per-project sticky defaults. Agents themselves can request launches,
  gated behind a `LaunchApproval` pending action driven by the `/sase_run` generated skill.

Design invariants locked across both epics (do not contradict them in the manual):

1. **No custom status strings.** Semantic status sets (`src/sase/agent/status_buckets.py`) are closed; custom roles get
   generic RUNNING/DONE semantics. v2 Phase 9 adds *display labels* on top — presentation only, buckets unchanged.
2. **No `%!` inline-shell directive; no root-level bash/python rows.**
3. **v1 metadata is the compatibility contract.** A `%n(foo, reviewer)` member is field-indistinguishable from a
   runner-created follow-up, so the v2 evaluator handles both with no migration (pinned by parity tests).
4. **User-initiated launches are ungated; agent-initiated launches require `LaunchApproval`.**

**Glossary caveat:** this feature uses the runner's double-dash family model (`foo--reviewer`). The repo memory
glossary still uses "agent family" for the `--` model but describes dot-separated names separately as **agent hoods**
(`foo.bar`). `docs/xprompt.md:897-900` carries the proposed rewording; the manual should adopt the `--`-lineage
definition and mention hoods as a distinct TUI concept.

## 2. v1 — User-Initiated Family Extension

### 2.1 `%n(parent, suffix)` grammar

Parsing lives in `src/sase/agent/family_attach.py` (`parse_name_directive_args`); dispatch only happens for the
**paren form** (`src/sase/xprompt/_directive_collect.py:150-183`). The colon form (`%n:reviewer`) is always plain
naming and never attaches.

| Form | Meaning |
| --- | --- |
| `%n(name)` / `%name(name)` / `%n:name` | Plain agent name (unchanged behavior) |
| `%n(parent, suffix)` | Family attach: launch as `<family-base>--<suffix>` |
| `%n(parent, @)` | Family attach with the next free numeric suffix |

Strict rejections (v1 deliberately converted the old silent-drop behavior into errors); each is a launch-blocking
`DirectiveError`:

| Input | Error message |
| --- | --- |
| Keyword args, e.g. `%n(foo, run_status=X)` | `Unsupported keyword on %n: run_status=. Use %n(parent, suffix) for family attach; keyword arguments are not supported.` |
| Three or more positionals | `%n accepts at most two positional arguments. Use %n(parent, suffix) for family attach.` |
| Empty parent or suffix | `%n(parent, suffix) requires both parent and suffix.` |
| Suffix with separator spelling (`.reviewer`, `-reviewer`, `--reviewer`) | `Invalid %n family suffix '...'. Pass the bare suffix without a family separator, e.g. %n(parent, reviewer).` |
| Other invalid suffix chars (regex is `^[A-Za-z0-9_]+$`) | `Invalid %n family suffix '...'. Use letters, numbers, and underscores only, or @ to allocate the next free suffix.` |
| Raw `--` in a *plain* name (`%name:foo--bar`) | `Agent name 'foo--bar' cannot contain '--'; double dash is reserved for agent-family phases.` (the reserved-separator guard is unchanged — attach is the only sanctioned way to get a `--` name) |

### 2.2 Parent resolution

Resolution runs at **launch-preparation time** (not just parse time) via the Rust binding
`resolve_agent_family_parent` with a Python fallback (`family_attach.py:575-626`):

- Candidates: the current project's `ace-run` artifacts (active + history + hidden).
- A candidate matches if its name or workflow name equals `parent`, or its name starts with `parent--`.
- **Newest timestamp wins**; dismissed identities are dropped among ties; a terminal winner resolves immediately, a
  running winner triggers queueing (§2.5).

Failure messages (all abort before any agent spawns, and surface on the launching surface — CLI stderr, TUI toast,
Telegram reply):

- Absent: `Cannot attach family member with %n(<parent>, <suffix>): parent agent '<parent>' was not found in project '<project>'.`
- Dismissed: `Cannot attach family member to dismissed parent '<parent>'. Revive the parent from the Agents tab before using %n(parent, suffix).`
- Ambiguous: `Cannot attach family member to '<parent>': multiple newest parent candidates matched (<name@ts>, ...). Use the exact parent after dismissing or reviving duplicates.`

### 2.3 Suffix → role mapping, `@` allocation, collisions

`AGENT_FAMILY_SEPARATOR = "--"` and the reserved set live in `src/sase/plan_chain.py`:

| Suffix argument | Role (`agent_family_role`) | Statuses |
| --- | --- | --- |
| `plan`, `q`, `code`, `epic`, `legend`, `commit` | The corresponding built-in role | Built-in role statuses (e.g. coder statuses for `code`) |
| Numeric, or `@` | `feedback` (a feedback/Q&A round) | Feedback-round statuses |
| Any other word (`reviewer`, `tester`, `improve_plan`, ...) | The word itself (open set, generic role) | Generic RUNNING/DONE (custom display labels come from v2 role definitions, never from the launch site) |

- `@` normalizes to the `--@` template and allocates the lowest free numeric slot via
  `allocate_agent_family_child_suffix`; `base`, `base--plan`, and `base--0` are always reserved so `@` never collides
  with the planner/root rows.
- The composed name is `<family-base>--<suffix>` where the family base comes from the parent's `agent_family` metadata
  (falling back to `agent_family_base(parent_name)`).
- Collision: `Agent family member '<name>' already exists. Use %n(<parent>, @) to allocate the next free suffix.`

### 2.4 Metadata and inheritance contract

An attached member's `agent_meta.json` is **field-indistinguishable from a runner-created follow-up**
(`create_followup_artifacts`, `src/sase/axe/run_agent_helpers_artifacts.py`); this is the explicit v1→v2 compatibility
contract, pinned by `test_family_attach_metadata_matches_runner_followup_and_tui_family_child`.

- Written: `name`, `workflow_name` (= family base), `role_suffix` (`--<suffix>`), `agent_family` (= family base),
  `agent_family_role`, `parent_timestamp` + `plan_chain_parent_timestamp` (= the resolved parent artifact's timestamp).
- Inherited from the parent: `workspace_dir`, `workspace_num`, `changespec_name`, `cl_name` (project/workspace scope).
- From the launch site via normal directive resolution: model, effort. No chat/session inheritance unless the user
  explicitly forks.
- **`SASE_PLAN` rule:** exported only for `code`-role members whose parent family has a committed/archived plan,
  mirroring the runner handoff rules.

### 2.5 Queueing under running parents

If the parent is still running, the child launches **immediately** and parks in the existing wait barrier — an
implicit, **identity-keyed** wait dependency (no second queue mechanism):

- The dependency records the parent's `project_name`, `timestamp`, `artifact_dir`, and `name` (persisted as
  `wait_for_artifacts` in the child meta), so a later same-named launch can never satisfy or steal the wait
  (`src/sase/core/wait_dependency_resolution.py`).
- TUI: the queued child renders as a **WAITING family-member child row folded under the running parent** (v1 Phase 1
  normalized workflow-step children and family-member children into one child-linkage model and made WAITING legal on
  child rows; `Agent.is_family_member_child`).
- **Success →** child starts. Success outcomes are `done.json` `completed` *and* `plan_rejected`; parent terminal
  statuses `DONE`, `PLAN DONE`, `TALE DONE` all map to `completed`. For a family-root parent, the whole generation
  aggregates: resolved only when all members resolved and any succeeded.
- **Failure → cancel.** `failed` / `killed` / `stopped` (and `repeat_stopped`) cancel the queued child to **STOPPED**
  (an existing terminal status — no new status strings): `done.json` gets `outcome: "stopped"`,
  `queue_cancelled: true`, `failed_dependencies`, and
  `error: "Queued launch cancelled because dependency failed: <name@timestamp>"`, and a notification is sent
  (`notify_workflow_complete` with notes `Queued agent @<name> stopped` / `Parent dependency failed: ...` and a
  `JumpToAgent` action). The stopped child deliberately does **not** satisfy downstream `%wait`s.
- A queued child never waits forever and never runs after a failed parent (locked decision 6 of the v1 epic).

### 2.6 `#with_feedback` and `#with_q_and_a`

Bundled embeddable xprompts (`src/sase/xprompts/with_feedback.yml`, `with_q_and_a.yml`). Pure prompt assembly — they
render the exact same bodies the runner produces for feedback-replan and answered-Q&A rounds (byte-parity tested
against the extracted helpers `src/sase/main/feedback_prompt.py` and `src/sase/main/qa_prompt.py`).

| Reference | Inputs | Behavior |
| --- | --- | --- |
| `#with_feedback` | `feedback` (text, required; fills from the `:: text` shorthand), `parent` (line, default `""`) | Reads the parent's prompt artifact (`followup_prompt.md` → newest `*_prompt.md` → `raw_xprompt.md`) and appends the feedback as an `### Additional Requirements` bullet, merging prior Q&A rounds in front |
| `#with_q_and_a` | `prompt` (text, required; `::` shorthand), `qa_file` (path, required) | Appends rendered Q&A rounds from the JSON file; the block is wrapped in `%xprompts_enabled:false ... true` so literal `#xprompt` text in answers never expands |

- `qa_file` accepts a single `{questions, response}` object, `{rounds: [...]}`, or a top-level list; `response` may be
  reconstructed from `answers`/`global_note`. Errors are loud and specific (`qa_file not found: ...`,
  `qa_file is not valid JSON: ...`, `qa_file round <n> must contain a 'questions' list`, ...).
- `#with_feedback` errors: `parent is required`, `unknown parent agent: <parent>`,
  `no prompt artifact found for parent agent '<parent>' at <dir>`.
- **Composition sugar (5f.5):** `#with_feedback` defaults `parent` from a co-occurring `%n(parent, suffix)` in the same
  `---` prompt segment (fenced-block aware; explicit `parent=` always wins). `#with_q_and_a` intentionally has no such
  inference.

Canonical composed usage:

```text
%n(planner, @) #with_feedback:: Add failure handling before coding.
%n(planner, reviewer) #with_feedback(parent=planner):: Re-check the API shape.
%n(planner, @) #with_q_and_a(qa_file=/tmp/qa_rounds.json):: Continue with the base prompt.
```

### 2.7 Surfaces

Family attach works from every normal user launch surface (CLI `sase run`, TUI prompt bar, Telegram/mobile) because
the constraint check runs in shared launch preparation; failures render on the launching surface. In multi-agent `---`
prompts, `%n` is segment-local: each segment prepares and spawns through its own launch slot. User-typed `%n` is never
gated by `LaunchApproval` (that gate is only for agent-initiated launches, §3.7).

## 3. v2 — Lifecycle-Initiated Family Extension

### 3.1 The plan-approval choice registry

`src/sase/plan_approval_choices.py` is now the single source of truth for the approval-choice vocabulary (previously
hard-coded in five places). Eight frozen records (`PLAN_APPROVAL_CHOICE_RECORDS`):

| id | Label | Protocol (action / commit_plan / run_coder) | Modal key (custom / review) | CLI kind | Archives plan | Auto-eligible |
| --- | --- | --- | --- | --- | --- | --- |
| `approve` | Approve | approve / no / yes | `a` / `a` | `approve` | yes | yes |
| `run` | Run | approve / no / yes | — | — | **yes (the 5g.2 fix)** | no |
| `tale` | Tale | approve / yes / yes | `t` / `t` | `tale` | yes | yes |
| `epic` | Epic | epic / yes / yes | `e` / `E` | `epic` | yes | yes |
| `legend` | Legend | legend / yes / yes | `l` / `L` | `legend` | yes | no |
| `commit` | Commit | approve / yes / no | — | — | `commit` | yes | no |
| `reject` | Reject | — | — | — | no | no |
| `feedback` | Feedback (requires feedback text) | — | — | — | no | no |

Notable derived sets: auto modes accept only `approve`/`tale`/`epic`; remote (Telegram/mobile) choices are
`approve, run, reject, epic, legend, feedback`. **The deliberate behavior change:** the `run` choice (the
Telegram/mobile "Approve"/"Run" button) previously skipped the plan-archive side effect; it now archives the plan into
`sdd/tales/YYYYMM/` exactly like an interactive Approve (fix in `plan_approval_actions.py` via
`approval_choice_archives_plan`).

### 3.2 Typed events + the `standard_plan_chain` evaluator

The architectural core (5g.3): "what happens next in a family" is answered by **data** (a family definition evaluated
by a pure evaluator) instead of hard-coded branches. Modules: `src/sase/agent_family/standard_plan_chain.py` (facade
over `standard_plan_chain_definition.py`, `standard_plan_chain_models.py`, `standard_plan_chain_evaluator.py`).

- **Events:** `plan_submitted`, `questions_submitted` (from the legacy `.sase_plan_pending` / `.sase_questions_pending`
  markers, which still drive the exec loop — the evaluator is layered on top with golden-harness-proven parity), and
  `role_completed` (§3.3). Gate renderers: `plan_approval`, `user_question`.
- **Built-in definition:** `standard_plan_chain` (id, version 1, entry role `root`) declares roles
  root/plan/q/feedback/code/epic/legend/commit with their suffixes and prompt templates, gates
  (`plan_review` → the §3.1 registry; `user_questions` returns to the interrupted role), per-choice target roles, and
  curated side-effect ids (`write_sdd`, `commit_sdd`, `set_sase_plan_env`, `launch_epic_creator`, ...). The compiled
  definition is SHA-256 hashed.
- **Family state on artifacts:** new additive `agent_meta.json` fields — `agent_family_config_id`,
  `agent_family_config_version`, `agent_family_config_hash`, `active_gate_id`, `active_gate_renderer`, `family_state`
  (`current_role`, `current_role_suffix`, `feedback_count`, `qa_round_count`, `saved_chat_suffixes`, `visit_counts`),
  and `agent_family_custom_role` (a full role snapshot for custom roles). Old artifacts without these fields remain
  valid; active runs evaluate against their snapshotted definition hash, so editing a definition mid-run cannot
  destabilize the run.
- `handle_plan_marker` / `handle_questions_marker` / `handle_accepted_plan` are now thin executors of evaluator
  decisions (`evaluate_plan_approval_transition`, `evaluate_questions_transition`, `evaluate_handoff_event`).
- The whole restructure is pinned by the **golden harness** `tests/plan_chain_golden/` (pytest marker
  `plan_chain_golden`, 5g.1) — response-JSON and prompt-body snapshots for every choice on every writer path.

### 3.3 `role_completed`: the after-code seam

Before v2 there was *no* seam after the coder — the exec loop broke unconditionally when a follow-up completed. Now
(5g.4) runner finalize emits `role_completed` (payload: `outcome` — currently always `"success"` — and
`artifacts_ref`; the role is read from the completed artifact's `agent_family_role`) for every family follow-up that
completes un-killed (uniformly for code/epic/legend; kills never emit it — the marker path wins).

The standard chain maps `role_completed` to terminate, so default behavior is unchanged. Custom roles placed
`after: code` (etc.) hook this event: the evaluator selects an active custom role placed after the completed role, and
the loop continues into it instead of breaking. Composition rule: post-code members run **after** the coder's
reconstructed embedded VCS refs (`#propose`/`#commit` post-steps) — a `tester` tests the proposed CL; "tester blocks
propose" is explicitly deferred.

### 3.4 `kind: agent_family` YAML — custom roles as data

Users define custom family roles declaratively (5g.5). Loader/validator:
`src/sase/agent_family/custom_definitions/` (`models.py`, `loading.py`, `validation.py`, `discovery.py`). A YAML file
is recognized only when its top-level mapping has `kind: agent_family`.

**Top-level fields:** `kind: agent_family`; `schema_version: 1` (must equal 1); `id` (required,
`^[A-Za-z][A-Za-z0-9_]*$`); `version` (required positive int); `extends` (optional, only `standard_plan_chain` is
accepted and it is the default); `roles` (required non-empty mapping keyed by role id).

**Per-role fields** (unknown keys are load errors):

| Field | Required | Values / default | Notes |
| --- | --- | --- | --- |
| `suffix` | no | default `--<role_id>`; must match `^--[A-Za-z0-9_]+$` | Must not be a standard reserved suffix; legacy `.`/`-` spellings rejected |
| `prompt_template` | yes | an xprompt reference string | Validated against the catalog; format placeholders: `plan_file`, `source_artifacts`, `artifacts_ref`, `outcome`, `source_role`, `role` |
| `placement` | yes | mapping with required `after: <role>` | Binds to gate insertion (`after: plan`) or `role_completed` (`after: code`, ...) |
| `on_done` | yes | `re_review` \| `continue` \| `terminate` | `re_review` sends the role's output back into the plan gate |
| `on_failure` | yes | `notify_and_continue` \| `notify_and_stop` | |
| `auto` | **yes — no default** | `run` \| `skip` | Explicit auto-mode behavior; definitions without it are rejected at load |
| `max_visits` | no | positive int, default `3` | Loop cap; exhaustion hard-stops with `custom_role_cap_exhausted` recorded |
| `default` | no | bool, default `false` | Whether the member is toggled on by default at the gate |
| `label`, `done_label` | no | ≤ 24 chars, `^[A-Za-z0-9][A-Za-z0-9 _/-]*$` | Display-only (§3.6) |
| `delegated_budget(s)` | no | reserved | Accepted + snapshotted, not interpreted (future agent-spawn budgets) |

**Discovery** scans `*.yml`/`*.yaml` in the same directories as xprompts, later overriding earlier by `id`: bundled
package xprompts → plugin `sase_xprompts` resources → `~/.config/sase/xprompts/<project>/` → workspace `.xprompts/` and
`xprompts/` → the general xprompt search paths. Invalid files are skipped with a recorded load issue (surfaced as
`skipped: <source>: <error>` by `sase xprompt list`). Definitions appear in `sase xprompt list` JSON with
`"type": "agent_family"` and a role-summary preview (`sase xprompt explain` does *not* cover them). Rust-catalog
visibility is an explicit non-goal.

**Flagship examples** ship as *inactive* templates under `src/sase/xprompts/examples/agent_families/` (deliberately
outside the search path — copy one into an active xprompts dir to enable it), with prompt-template xprompts
`agent_family_improve_plan.md` / `agent_family_tester.md`:

```yaml
# improve_plan.yml — re-review loop after the planner
kind: agent_family
schema_version: 1
id: improve_plan
version: 1
extends: standard_plan_chain
roles:
  improve_plan:
    suffix: "--improve_plan"
    label: "IMPROVING PLAN"
    done_label: "PLAN IMPROVED"
    prompt_template: "agent_family_improve_plan:{plan_file}"
    placement:
      after: plan
    on_done: re_review
    max_visits: 3
    on_failure: notify_and_stop
    auto: skip
```

```yaml
# tester.yml — post-coder verification
kind: agent_family
schema_version: 1
id: tester
version: 1
extends: standard_plan_chain
roles:
  tester:
    suffix: "--tester"
    label: "TESTING"
    done_label: "TESTED"
    prompt_template: "agent_family_tester:{source_artifacts}"
    placement:
      after: code
    on_done: terminate
    max_visits: 1
    on_failure: notify_and_continue
    auto: run
```

**v1 interop:** `%n(foo, improve_plan)` where `improve_plan` is a defined role records the role id identically;
manually-attached and evaluator-inserted members are indistinguishable to the TUI (grouping, statuses, dismissal) —
parity-tested.

### 3.5 Approval-gate member options + sticky defaults

The north-star UX (5g.6): at plan-approval time the user chooses which defined custom members run.

- **TUI:** `ApproveOptionsModal` (the existing `c`ustom path — no new top-level modal keys) renders an "Also run:"
  section; digit keys `1`-`9` toggle members; rows show `[x]/[ ] <label>  after <role>`. Default-checked state comes
  from role `default` merged with project config.
- **CLI:** `sase plan approve ... -w/--with ROLE` and `-W/--without ROLE` (both repeatable). Same role in both flags →
  `member option specified with both --with and --without: <ids>`; unknown role →
  `unknown plan-approval member option: <ids>` (exit 2).
- **Payloads:** `plan_request.json` carries `member_options` (id, label, placement, suffix, auto, defaults, config
  id/hash, source path) and `default_member_ids`; `plan_response.json` carries `selected_member_ids`. A response
  without explicit selection falls back to the request's defaults. Selection is gate-scoped: `None` preserves
  definition defaults, an empty tuple means "run no custom members".
- **Sticky per-project defaults:** `sase.yml` key `agent_family.plan_approval.default_members` — a mapping of role id →
  bool (a plain list of ids is also tolerated; schema in `src/sase/config/sase.schema.json`). Precedence: explicit gate
  selection > project config override > the role definition's own `default`.
- **Remote surfaces:** Telegram/mobile approvals get no toggles in v2 (anti-option-explosion decision); the
  notification preview appends `Also run: <ids>` so remote users see what will run, and the response's missing
  selection applies the sticky defaults.

### 3.6 Auto modes, loop caps, and display labels

- **Auto modes (`%auto` / `%a`):** the auto path only enables members whose role declares `auto: run` (intersected with
  the default ids); `auto:` being schema-required with no default is the guard against the "testers that never ran"
  bug class. Auto plan approval itself remains limited to `approve`/`tale`/`epic`.
- **Loop caps:** every role has `max_visits` (default 3). `improve_plan`-style `on_done: re_review` loops increment
  `visit_counts` in family state; at the cap the evaluator hard-stops — the run records
  `custom_role_cap_exhausted: <role_id>` (plan gate) or `custom_role_terminal_reason`/`custom_role_terminal_role`
  (`role_completed` gate) and terminates through the normal finalize path. A snapshot guard also prevents a custom role
  from chaining after itself.
- **Display labels (5g.9):** role `label`/`done_label` flow into `Agent.custom_role_label`/`custom_role_done_label` and
  surface via the display-only `Agent.display_status` — shown when the semantic status is RUNNING/DONE respectively.
  Buckets, colors, dismissal, mirroring, and waiting all key off the unchanged semantic status; only the visible text
  changes. Launch-site label kwargs stay rejected — labels come only from role definitions.

### 3.7 Agent-initiated launches: `LaunchApproval` + `/sase_run`

v2 Phases 7–8 gate agent-initiated spawning behind explicit user approval.

**The gating rule** (single seam, `running_agent_context_requires_launch_approval()` = `SASE_AGENT` env set): when a
*running agent* invokes `sase run`, the launch is diverted into a `LaunchApproval` request instead of spawning
(source surface `agent_skill`). User-typed surfaces (CLI without `SASE_AGENT`, TUI, Telegram/mobile bridge) launch
directly — including user-typed `%n` family attach, which stays ungated (regression-tested). An *agent* writing
`%n(foo, reviewer)` in its requested prompt is gated like any other agent-initiated launch.

**Request flow:**

- `sase launch request [-f FILE | PAYLOAD | @PATH] [-p PROMPT] [-r REASON] [-a required] [-m MAX_SLOTS] [-o text|json]`.
  Request JSON schema (version 1): `schema_version: 1`, `prompt` (required), `reason` (optional, defaults to
  `"Detached launch requested."`), `approval` (only `"required"` is accepted — **no auto-approve exists for launches**;
  every agent-initiated launch needs explicit approval), `max_slots` (default 1; the planned fan-out must fit or the
  request fails with `max_slots_exceeded`), optional `family_type`.
- Files land in `~/.sase/launch_requests/<request_id>/` (`request_id` = `launch-<uuid>`): `launch_request.json` (the
  full preview payload — slots, planned names, prompt SHA-256/snippets, `all_or_nothing: true` — plus the normalized
  request, requester env, and dispatch cwd/prompt) and `launch_preview.md` (human-readable preview). A priority
  notification (`action: LaunchApproval`) is sent.

**Resolution:**

- TUI: `LaunchApprovalModal` renders the preview; `a` approve, `r` reject, `q`/escape cancel.
- CLI: `sase launch approve <selector>` / `sase launch reject <selector> [-f FEEDBACK]`, where `<selector>` is the
  request id, notification id, or a unique notification-id prefix.
- `launch_response.json` is written **write-once** (`{"action":"approve"}` or `{"action":"reject","feedback":...}`);
  a second resolution attempt fails with `conflict_already_handled`. On approval the request is **revalidated and
  re-planned fresh** at dispatch time (cwd re-checked, prompt re-parsed) and dispatched through the normal launch path;
  success annotates the response with `dispatch_status: "launched"` and `launched_count`. Batches are all-or-nothing.

**The `/sase_run` generated skill** (`src/sase/xprompts/skills/sase_run.md`, deployed via the `sase skill init`
pipeline) teaches agents to: never run `sase run`/`sase run -d` directly; write the request JSON and submit with
`sase launch request -f launch_request.json -o json`; embed `%n(parent, suffix)` / `%n(parent, @)` inside the requested
prompt to attach the launch to a family; and poll the returned `response_file` for the approve/reject outcome
(respecting rejection feedback rather than spawning anyway).

Mobile support rides `execute_mobile_launch_action` + the mobile notification snapshot (action `LaunchApproval`,
`launch_preview.md` as the display file); Telegram rendering is delegated to the `sase-telegram` plugin.

## 4. Usage Recipes (manual-ready)

1. **Feedback round on a finished (or running) planner:**
   `%n(planner, @) #with_feedback:: Add failure handling before coding.` — allocates the next feedback suffix, infers
   `parent=planner` from the `%n`, and builds the same replan body the runner would.
2. **Answered-Q&A follow-up:** `%n(planner, @) #with_q_and_a(qa_file=/tmp/qa_rounds.json):: Continue with the base prompt.`
3. **Attach an ad-hoc named member:** `%n(foo, reviewer) Review the diff produced by this family.` — creates
   `foo--reviewer` with `agent_family_role: reviewer`, grouped under `foo` in the Agents tab.
4. **Queue behind a running parent:** same syntax; the child appears as a WAITING child row and starts when that exact
   parent artifact completes successfully (cancelled to STOPPED with a notification if the parent fails).
5. **Enable a custom lifecycle role:** copy `src/sase/xprompts/examples/agent_families/tester.yml` (and its prompt
   xprompt) into an active xprompts directory, adjust, verify it shows up in `sase xprompt list`.
6. **Choose members at approval time:** TUI — `c` on the plan approval modal, digits `1`-`9` toggle "Also run" members;
   CLI — `sase plan approve <id> --with tester --without improve_plan`.
7. **Make a member the project default:** in the project `sase.yml`:
   `agent_family: { plan_approval: { default_members: { tester: true } } }`. Remote approvals and `%auto` flows (for
   `auto: run` roles) then include it automatically.
8. **Agent-initiated spawn:** the agent uses `/sase_run` → `sase launch request -f launch_request.json -o json`; the
   user approves via the TUI modal or `sase launch approve <id>`.

## 5. Documentation Status and Gaps

**Already documented (v1):** `docs/xprompt.md` covers the `%n` two-argument form, `@` allocation, reserved vs custom
suffixes, running-parent queueing + cancel policy, collision guidance, the `#with_feedback`/`#with_q_and_a` table with
examples and the `qa_file` shape, the segment-local multi-agent note, the submitted-plan `%wait` exception on the
`<base>--plan` row, and the glossary rewording note (`docs/xprompt.md:868-900, 1026-1031, 1090-1108`).

**Undocumented (v2 — the manual must author these from scratch):**

- The `kind: agent_family` YAML schema, discovery/precedence, and the bundled inactive examples (§3.4).
- `sase plan approve --with/--without` and the `ApproveOptionsModal` member toggles (§3.5) — absent from `docs/cli.md`
  and `docs/ace.md`.
- The `agent_family.plan_approval.default_members` config key (§3.5) — absent from `docs/configuration.md`.
- The `run` choice's behavior change (remote Approve now archives the plan) — worth a changelog/manual callout.
- The whole `sase launch request/approve/reject` surface and `LaunchApproval` flow (§3.7) — `docs/cli.md` has no
  `sase launch` entry; the only shipped "doc" is the generated `/sase_run` skill itself.
- Custom-role display labels and the label-vs-bucket split (§3.6).
- The evaluator/family-state architecture (§3.2–3.3) for an "under the hood" manual section.

**Suggested manual structure:** (a) concept: families, roles, static chain vs dynamic extension; (b) extending
families by hand (`%n`, xprompts, queueing); (c) custom lifecycle roles (YAML how-to + flagship examples); (d) choosing
members at the plan gate (TUI/CLI/config/remote/auto); (e) agent-initiated launches (`/sase_run`, `sase launch`);
(f) reference tables (grammar, YAML fields, choice registry, error messages); (g) under the hood (evaluator, events,
metadata, compatibility guarantees).

## 6. Key Code and Test Anchors

- v1 attach: `src/sase/agent/family_attach.py`, `src/sase/xprompt/_directive_collect.py`, `src/sase/plan_chain.py`,
  `src/sase/axe/run_agent_directives.py`, `src/sase/core/wait_dependency_resolution.py`,
  `src/sase/axe/run_agent_runner.py` (queue cancel), `src/sase/axe/run_agent_helpers_artifacts.py` (metadata contract);
  tests `tests/test_dynamic_agent_family_attach.py`.
- Follow-up xprompts: `src/sase/xprompts/with_feedback.yml`, `with_q_and_a.yml`, `src/sase/main/feedback_prompt.py`,
  `src/sase/main/qa_prompt.py`; tests `tests/test_followup_prompt_helpers.py`.
- v2 registry/evaluator: `src/sase/plan_approval_choices.py`, `src/sase/agent_family/standard_plan_chain*.py`,
  `src/sase/agent_family/custom_definitions/`, `src/sase/axe/run_agent_exec*.py`,
  `src/sase/axe/run_agent_family_metadata.py`; golden harness `tests/plan_chain_golden/` (marker `plan_chain_golden`);
  tests `tests/test_standard_plan_chain_evaluator.py`, `tests/test_agent_family_custom_definitions.py`,
  `tests/test_plan_approval_choices.py`, `tests/test_approve_options_modal_state.py`.
- Launch approval: `src/sase/agent/launch_request.py`, `src/sase/agent/launch_preview.py`,
  `src/sase/launch_approval_actions.py`, `src/sase/main/parser_launch.py` + `launch_handler.py`,
  `src/sase/main/query_handler/_launch.py` (the gate), `src/sase/ace/tui/modals/launch_approval_modal.py`,
  `src/sase/xprompts/skills/sase_run.md`; tests `tests/test_launch_approval.py`, `tests/test_special_cases.py`
  (agent-context gating).
- TUI labels/rows: `src/sase/ace/tui/models/agent.py` (`display_status`, `is_family_member_child`),
  `_agent_status_apply.py`, `_agent_status_family.py`,
  `src/sase/ace/tui/widgets/_agent_list_render_agent.py`; visual golden
  `tests/.../agents_custom_role_labels_120x40.png`.
- Beads: `sase-5f` (+ `.1`–`.5`), `sase-5g` (+ `.1`–`.9`); closeout tale `sdd/tales/202607/close_out_sase_5f_epic.md`.
