# Agent Families

A **plan-chain agent family** is the group of agents that share a `--`-separated base name: `foo`, `foo--plan`,
`foo--code`, `foo--plan-2`, and so on. Families are how SASE tracks a unit of work as it moves through planning,
questions, feedback rounds, coding, and commit follow-ups; ACE groups every member under the same root entry on the
Agents tab.

Historically, families only grew from the inside: the runner's plan/questions handoff was the sole mechanism that could
attach a new member, along hard-coded transitions (plan approved → spawn coder, questions answered → spawn follow-up).
**Dynamic agent families** make family extension a first-class primitive in two complementary ways:

- **User-initiated extension.** Attach a new member to any existing family by writing `%n(parent, suffix)` in an
  ordinary prompt, from any launch surface (CLI, TUI, Telegram/mobile). See
  [Extending a Family by Hand](#extending-a-family-by-hand).
- **Lifecycle-initiated extension.** Define custom roles declaratively in `kind: agent_family` YAML (for example, an
  `improve_plan` reviewer after the planner, or a `tester` after the coder), toggle them per approval at the plan gate,
  and set per-project sticky defaults. Agents themselves can request launches, gated behind an explicit `LaunchApproval`
  pending action. See [Custom Lifecycle Roles](#custom-lifecycle-roles) and
  [Agent-Initiated Launches](#agent-initiated-launches).

Glossary note: agent families use the runner's double-dash lineage model (`foo--reviewer`). Dot-separated names such as
`foo.bar` are a distinct ACE TUI concept — agent _hoods_ and _neighbors_ — unrelated to plan-chain family membership.

## Family Roles

Every family member records an `agent_family_role` derived from its name suffix:

| Suffix                                          | Role                              | Status labels                                                                                               |
| ----------------------------------------------- | --------------------------------- | ----------------------------------------------------------------------------------------------------------- |
| `plan`, `q`, `code`, `epic`, `commit`           | The corresponding built-in role   | Built-in role statuses (e.g. coder statuses)                                                                |
| Numeric (`@` in `%n` allocates the next number) | `feedback` (a feedback/Q&A round) | Feedback-round statuses                                                                                     |
| Any other word (`reviewer`, `tester`, ...)      | The word itself (open set)        | Generic RUNNING/DONE, unless a custom role definition supplies [display labels](#custom-role-status-labels) |

The reserved suffixes are exactly the built-in plan-chain roles; custom role definitions may not reuse them.

## Extending a Family by Hand

The two-argument `%n(parent, suffix)` directive attaches a new agent to an existing family from any normal user launch
surface. `%n(parent, @)` allocates the next free numeric feedback suffix. If the parent is still running, the child
launches immediately as a WAITING child row under the parent and starts when that exact parent artifact completes
successfully; if the parent fails, is stopped, or is killed, the queued child is cancelled to `STOPPED` with a
completion notification.

Two bundled xprompts assemble the classic follow-up prompt bodies — `#with_feedback` (plan feedback rounds) and
`#with_q_and_a` (answered question rounds). They only build prompt text; `%n` is what launches and attaches the agent:

```text
%n(planner, @) #with_feedback:: Add failure handling before coding.
%n(planner, @) #with_q_and_a(qa_file=/tmp/qa_rounds.json):: Continue with the base prompt.
%n(foo, reviewer) Review the diff produced by this family.
```

In a multi-agent prompt, a later segment can attach to a parent explicitly named in an earlier segment of the same
prompt:

```text
%n:foo Plan the change.
---
%n(foo, reviewer) Review foo's plan.
```

The in-batch parent is treated as still running, so the attached member is queued as a WAITING child and starts after
the parent completes successfully. This only applies to earlier static names such as `%n:foo` or `%n(foo)`;
template-named and auto-named parents are not available for same-prompt `%n(parent, suffix)` resolution.

The full grammar, parent-resolution rules, queueing semantics, error messages, and the follow-up xprompt reference live
in the [XPrompts doc](xprompt.md#supported-directives); the `#with_feedback` / `#with_q_and_a` reference is under
[Bundled Follow-Up XPrompts](xprompt.md#bundled-follow-up-xprompts).

A manually attached member writes the same family metadata as a runner-created follow-up, so ACE groups, statuses, and
dismisses it like any other member. A manual attach does not run the custom lifecycle machinery, though: even when the
suffix matches a defined custom role (`%n(foo, tester)`), the member runs your prompt with generic RUNNING/DONE labels.
Display labels, prompt templates, and visit caps apply only to members the family evaluator inserts itself (see
[Custom Lifecycle Roles](#custom-lifecycle-roles)).

## Custom Lifecycle Roles

Custom family roles are defined declaratively in YAML files with `kind: agent_family`. A definition extends the built-in
`standard_plan_chain` family and adds roles that run at specific points in the chain — after the planner (gated by plan
approval) or after the coder and other terminal roles (via role-completion events).

### Definition Format

A YAML file is recognized as a family definition only when its top-level mapping has `kind: agent_family`.

Top-level fields:

| Field            | Required | Notes                                                          |
| ---------------- | -------- | -------------------------------------------------------------- |
| `kind`           | yes      | Must be `agent_family`                                         |
| `schema_version` | yes      | Must be `1`                                                    |
| `id`             | yes      | Identifier matching `^[A-Za-z][A-Za-z0-9_]*$`                  |
| `version`        | yes      | Positive integer                                               |
| `extends`        | no       | Only `standard_plan_chain` is accepted (and it is the default) |
| `roles`          | yes      | Non-empty mapping keyed by role id                             |

Per-role fields (unknown keys are load errors):

| Field                 | Required | Values / default                                      | Notes                                                                                                                                                |
| --------------------- | -------- | ----------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------- |
| `suffix`              | no       | default `--<role_id>`; must match `^--[A-Za-z0-9_]+$` | Must not collide with the reserved suffixes (`--plan`, `--q`, `--code`, `--epic`, `--commit`)                                                        |
| `prompt_template`     | yes      | an xprompt reference string                           | Validated against the xprompt catalog; format placeholders: `plan_file`, `source_artifacts`, `artifacts_ref`, `outcome`, `source_role`, `role`       |
| `placement`           | yes      | mapping with required `after: <role>`                 | `after: plan` binds to the plan-approval gate; `after: code` (and other terminal roles) binds to role completion                                     |
| `on_done`             | yes      | `re_review` \| `continue` \| `terminate`              | Declared follow-on intent, validated and recorded in the run snapshot; looping is driven by the role's prompt template (see [Loop Caps](#loop-caps)) |
| `on_failure`          | yes      | `notify_and_continue` \| `notify_and_stop`            |                                                                                                                                                      |
| `auto`                | yes      | `run` \| `skip` (no default)                          | Whether `%auto` flows include this role; definitions without it are rejected                                                                         |
| `max_visits`          | no       | positive int, default `3`                             | Loop cap; at the cap the evaluator hard-stops the loop and terminates normally                                                                       |
| `default`             | no       | bool, default `false`                                 | Whether the member is toggled on by default at the plan gate                                                                                         |
| `label`, `done_label` | no       | ≤ 24 chars, `^[A-Za-z0-9][A-Za-z0-9 _/-]*$`           | Display-only status labels; see [Custom Role Status Labels](#custom-role-status-labels)                                                              |
| `delegated_budget(s)` | no       | reserved                                              | Accepted and snapshotted but not yet interpreted                                                                                                     |

### Discovery

Definitions are discovered from `*.yml`/`*.yaml` files in the same directories as xprompts, with later sources
overriding earlier ones by `id`:

1. Bundled package xprompts
2. Plugin `sase_xprompts` resources
3. `~/.config/sase/xprompts/<project>/`
4. Workspace `.xprompts/` and `xprompts/` directories
5. The general xprompt search paths

Invalid files are skipped with a recorded load issue (surfaced as `skipped: <source>: <error>` by `sase xprompt list`).
Valid definitions appear in `sase xprompt list` JSON output with `"type": "agent_family"` and a role-summary preview.

### Bundled Examples

Two flagship examples ship as **inactive** templates under `src/sase/xprompts/examples/agent_families/` (deliberately
outside the search path). Copy the `.yml` file into an active xprompts directory to enable it — the prompt templates it
references (`#agent_family_improve_plan`, `#agent_family_tester`) are already bundled and discoverable — then confirm it
appears in `sase xprompt list`:

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

Post-code members run after the coder's embedded VCS post-steps (`#propose`/`#commit`), so a `tester` tests the proposed
change; testers do not block the propose step.

## Choosing Members at the Plan Gate

When a family with defined custom members reaches plan approval, you choose which members run for that approval.

- **ACE TUI:** press `c` on the plan-approval modal to open the custom-approval dialog; it renders an "Also run:"
  section where digit keys `1`-`9` toggle members. Each row shows its toggle digit, a checkbox, the role id, and the
  role's placement — for example `1 [x] tester after code`. The default-checked state comes from each role's `default`
  merged with the project config.
- **CLI:** `sase plan approve <selector> --with <role>` and `--without <role>` (short forms `-w`/`-W`, both repeatable).
  Naming the same role in both flags or naming an unknown role fails with a clear error before the approval is written.

```bash
sase plan approve abcdef12 --with tester --without improve_plan
```

### Sticky Project Defaults

Set per-project defaults in `sase.yml` under `agent_family.plan_approval.default_members`, a mapping of role id to
boolean:

```yaml
agent_family:
  plan_approval:
    default_members:
      tester: true
```

Precedence: explicit gate selection > project config override > the role definition's own `default`.

### Remote Approvals and Auto Modes

- **Telegram/mobile approvals** have no member toggles; the notification preview appends `Also run: <ids>` so remote
  users see what will run, and the sticky defaults apply.
- **`%auto` / `%a` flows** only enable members that are both default-enabled (after the sticky defaults are applied) and
  declare `auto: run`. Auto plan approval itself remains limited to the `approve`, `tale`, and `epic` kinds.
- The remote `run` choice (the Telegram/mobile "Run" button) archives the approved plan into the resolved SDD tale path
  exactly like an interactive Approve. Use `sase sdd path plans` rather than assuming whether that root is in-tree, a
  legacy `.sase/sdd/` clone, or the split `--plans` companion.

### Loop Caps

Every role has a `max_visits` cap (default 3). A re-review loop arises when the role's prompt template resubmits a plan
(the bundled `improve_plan` template does exactly that), which brings the family back to the plan gate; each time the
evaluator inserts the role, its per-role visit count in family state increments. At the cap the evaluator stops
inserting it and the run terminates through the normal finalize path, recording the exhausted role in the run artifacts.
A custom role can never chain directly after itself.

## Custom Role Status Labels

A role's `label` and `done_label` replace the generic status text on the Agents tab while the member is RUNNING and
after it is DONE, respectively (for example `TESTING` / `TESTED`). Labels are presentation-only: status buckets, row
colors, dismissal, mirroring, and waiting behavior all key off the unchanged semantic status. Labels come only from role
definitions — they cannot be set from the launch site.

## Agent-Initiated Launches

User-initiated launches are never gated: prompts typed in the CLI, TUI, or Telegram/mobile — including user-typed
`%n(parent, suffix)` family attaches — spawn directly. When a **running agent** invokes `sase run`, the launch is
instead diverted into a **`LaunchApproval` request**: SASE previews the launch, sends a priority notification, and
spawns nothing until a human approves.

### Requesting a Launch

Agents use the generated `/sase_run` skill, which teaches them to write a structured request and submit it with:

```bash
sase launch request -f launch_request.json -o json
```

The request JSON (schema version 1) carries `schema_version: 1`, a required `prompt`, an optional `reason`,
`approval: "required"` (the only accepted value — there is no auto-approve for agent-initiated launches), `max_slots`
(default 1; the planned fan-out must fit), and an optional `family_type`. Inline payloads
(`sase launch request '<json>'` or `@path`) and plain prompt flags (`-p/--prompt`, `-r/--reason`) are also accepted.
`max_slots` is checked against the preview plan after SASE expands xprompts and fan-out directives. A plain request with
top-level `---` segment separators outside fenced code blocks normally plans one launch slot per non-empty segment, so
`max_slots` must cover that count or the request fails with `max_slots_exceeded`.

Request artifacts land in `~/.sase/launch_requests/<request_id>/`: `launch_request.json` (the full preview payload plus
the normalized request) and `launch_preview.md` (the human-readable preview shown by approval surfaces). A request may
embed `%n(parent, suffix)` in its prompt to attach the launch to a family.

Approving a request re-dispatches the stored prompt from the original request cwd through the normal launcher. The
preview step does not make `%` directives or `#` references literal; they remain live anywhere in the prompt. Literal
prompt syntax in docs, demos, or tests should be fenced or wrapped in `%xprompts_enabled:false` /
`%xprompts_enabled:true` disabled regions. Preflight with `sase xprompt expand '<prompt>'` when the prompt contains
literal directive examples.

### Approving or Rejecting

- **ACE TUI:** the launch-approval modal renders the preview; press `a` to approve, `r` to reject, `q`/escape to cancel.
- **CLI:** `sase launch approve <selector>` or `sase launch reject <selector> [-f <feedback>]`, where `<selector>` is
  the request id, notification id, or a unique notification prefix.

The response is write-once — a second resolution attempt fails as already handled. On approval the request is
revalidated and re-planned fresh at dispatch time, then dispatched through the normal launch path; multi-slot batches
are all-or-nothing. Rejection feedback is written into the response file so the requesting agent can read it and adjust
instead of spawning anyway.

## Under the Hood

The plan/questions handoff routes through typed events (`plan_submitted`, `questions_submitted`, `role_completed`)
evaluated against a family definition by the `standard_plan_chain` evaluator; "what happens next in a family" is
answered by data instead of hard-coded branches. `role_completed` fires for every runner-spawned follow-up that
completes un-killed, which is the seam custom `after: code` roles hook into; the standard chain maps it to terminate, so
default behavior is unchanged. (Members attached by hand with `%n` run outside the runner loop, so their completion does
not raise `role_completed`.)

Family runs snapshot their definition (`agent_family_config_id`/`version`/`hash`) and track progress in additive
`agent_meta.json` fields (`family_state` with current role, feedback/Q&A round counts, and per-role visit counts, plus
`agent_family_custom_role` for custom-role members). Artifacts written before these fields existed remain valid, and an
active run always evaluates against its snapshotted definition, so editing a definition mid-run cannot destabilize the
run.

Two invariants worth knowing:

- **No custom status strings.** Semantic status sets are closed; custom roles get generic RUNNING/DONE semantics with
  display labels layered on top.
- **v1 metadata is the compatibility contract.** A member attached with `%n` writes the same family metadata fields as a
  runner-created follow-up, so grouping, statuses, and dismissal work identically without migration. Only
  evaluator-inserted members additionally carry the custom-role snapshot that drives display labels and loop tracking.
