---
title: Plan format
description: The fields, validation rules, and decision sections used in SASE plans.
---

# Plan format

This page describes the structure and validation rules for SASE plan files.

## Plan Frontmatter Schema and Validation

Run `sase plan validate PLAN_FILE` while authoring a plan. The command selects the
schema from the plan's required top-level `tier: tale` or `tier: epic` property; the
former `-t/--tier` option has been removed. Ordinary schema validation accepts any
readable UTF-8 path and does not require `SASE_AGENT`, `SASE_ARTIFACTS_DIR`, or a
registered project context. Memory decisions also use host context for selector and
human-quote checks inside an agent; outside an agent, quote verification is deferred to
proposal. Validation reports problems in one pass with stable diagnostic codes, field
paths, and best-effort line numbers.

Every tale and epic requires these authored fields:

| Field   | Required | Rule                                                               |
| ------- | -------- | ------------------------------------------------------------------ |
| `tier`  | yes      | `tale` or `epic`; selects the validation schema                    |
| `title` | yes      | Non-empty human-readable plan title                                |
| `goal`  | yes      | Non-empty description of the outcome the plan is intended to reach |
| `model` | no       | Non-empty model value using the same syntax as `%model`            |

Tales additionally require `size: xsmall | small | medium`. A tale is work one follow-up
agent implements directly, so `large` and `xlarge` are invalid tale sizes and belong in
an epic plan instead. Authoring validation rejects a missing or over-sized tale `size`,
while launch validation normalizes both to `medium` with a warning so existing tales
launch.

SASE-managed `create_time`, `status`, `bead`, `bead_id`, `proposed_by`, and `project`
fields are accepted but never required. `project` records the SASE project for a
machine-local proposal and is stripped when the plan is archived into that project's
plan store. A plan may also declare [review decisions](#plan-decisions); their answers
and review stamps are written by SASE. A proposal may carry the transient `links:`
authoring inlet: a list of typed artifact relationships that `sase plan propose`
validates, persists, and removes before archiving; see
[Authoring links in a proposed plan](../../artifact_links.md#authoring-links-in-a-proposed-plan).
Plans with a `prompt` or `parent` property remain valid, but both are intentionally
omitted from canonical schema and authoring output because new links use the Markdown
header block; `parent` additionally reports a deprecation warning pointing at the
`PARENT` bullet. See the
[plan-frontmatter migration note](../upgrading/work-units.md#plan-frontmatter). Epics
may also carry the SASE-managed `parent_bead` field. Other unknown fields are errors. A
plan must start with valid, closed YAML frontmatter and contain a non-empty Markdown
body.

Epics additionally require an ordered, non-empty `phases` list. Optional `patch`
(`changespec` is also accepted) and integer `bug_id` metadata may be supplied; `bug_id`
requires the Patch association. The epic-only `parent_bead` associates an approved plan
with the bead under which SASE creates its child epic. Each phase requires a unique slug
`id`, a non-empty `title`, a `depends_on` list, and
`size: xsmall | small | medium | large | xlarge`. Dependencies may only name earlier
phases, cannot repeat, and cannot refer to the phase itself. Optional phase fields are
`description` and `model`. Only set a phase model when the user's prompt requested one;
for a phase that only exercises or observes a SASE agent feature and does no
consequential work, use `size: xsmall` instead of a cheap model override.

```yaml
---
tier: epic
title: Workspace GC rewrite
goal: Stale workspaces are collected safely
phases:
  - id: core
    title: GC planner and safety checks
    depends_on: []
    size: medium
  - id: cli
    title: Workspace GC command
    depends_on: [core]
    size: small
---
# Plan

Implement the validated workflow.
```

Epic-only fields on a tale produce warnings because they are inert when a human
downgrades an epic-authored plan. All other schema violations are errors. Human failures
always include the authoritative expected-schema table and a minimal valid example. Add
`-e/--explain` to print tier-specific authoring guidance before the result; in JSON mode
the same guidance is included as an `explanation` field. `-q/--quiet` suppresses a
successful human summary, but an explicitly requested explanation is still printed.

If `tier` is missing or is not `tale` or `epic`, validation fails with an actionable
hint and omits the explanation because no authored schema can be selected. To keep
reporting the other problems in the file, the implementation uses the tale schema as a
diagnostic fallback. Consequently, JSON reports `"tier": "tale"` and the expected tale
schema in this error case; that value does **not** mean SASE inferred a tale. The tier
diagnostic still fails the command. JSON stays on stdout while the tier hint is written
to stderr. Otherwise `-j/--json` returns `schema_version`, `ok`, the authored `tier`,
`path`, the complete diagnostics list, and the expected schema. Exit status is 0 for
valid plans, 1 for validation failures, and 2 for command-usage errors.

Plan Decisions add human text to `sase plan validate` output when the plan has
decisions. Outside an agent, the command prints `quote verification runs at propose`
(stdout in human mode, stderr in `--json` mode) before the result. After the human
render, or on stderr after the JSON object in `--json` mode, the command also prints the
Decision Sheet whenever the validated plan still has decisions. That includes the
outside-agent path. When an auto plan-approval action is active (`%auto`), one more line
follows the sheet: `auto-approved: every decision takes its default`. That line is not
printed merely because the process is inside an agent: it appears only when the live
`%auto` spelling covers the plan's tier, so a cross-tier plan under `%auto:tale` or
`%auto:epic` omits it and waits for review. At propose time the uncovered line reads
`%auto:<mode>` does not cover `<tier>` plans; this plan waits for review. In `--json`
mode stdout stays one JSON document: the sheet, the `%auto` note, and the outside-agent
quote-verification note live inside the `decisions` envelope. If agent-context host
checks add diagnostics, the plan is cleared and the sheet is skipped. Ordinary plans
without decisions keep the JSON-only contract.

## Plan Decisions

Plan decisions let a reviewer choose between explicit alternatives while approving a
tale or epic. Every surface shows the decisions next to the plan with their current
values filled in, and the primary action always approves exactly the values on display.
Plans without decisions keep their ordinary approval flow.

A decision's lifecycle runs from authoring to the coder. `sase plan validate` renders
the Decision Sheet the reviewer will see. `sase plan propose` echoes
`Plan Decisions: N (🧠 M)` before its handoff, plus an `%auto` note when the plan will
be auto-approved. Gate build freezes the definitions into `payload.decisions` and
compiles `decision_<id>` raw properties onto the approval options. The reviewer edits
values in ACE's Decisions panel, Telegram's decision keyboard, or the CLI's
`-D/--decide ID=VALUE`; submits carry the displayed review revision, and conflicting
values across selected options fail before acceptance. On approval, SASE stamps the
accepted answers into the durable plan (see Archive fields below); every implementer
then receives them mechanically as a host-written Reviewer decisions block, and an
auto-approved plan with decisions posts one quiet receipt. Automatic resolution runs the
agent's autonomy record through one core evaluator over explicit policy option IDs —
never the gate's primary branch or default selections — and records the deciding
`policy` block (`profile`, `selection`, `rule`, `outcome`, `value`, `option_ids`,
`source`, `revision`, `digest`) on the gate's request envelope, its creation result,
and, for automatic outcomes, its response.

Declare up to five decisions as a frontmatter map. Each decision needs an `ask` and a
`default`. Omitting `choices` makes it a boolean toggle; supplying a map of two to five
choices makes it a choice whose default must exactly name a choice key. An optional
`why` explains an ordinary decision's default. This complete tale illustrates a choice:

```markdown
---
tier: tale
title: Keyboard help overlay
goal: Pressing ? shows the available bindings
size: small
decisions:
  grouping:
    ask: How should the overlay group bindings?
    choices:
      pane: By pane, matching the footer hints
      mode: By keyboard mode
    default: pane
    why: Keep the same order as the footer
---

# Plan

Add a help overlay to the active pane.

> [!decision] grouping = pane Group bindings by pane.

> [!decision] grouping = mode Group bindings by keyboard mode.
```

Decision IDs start with a lowercase letter, contain only lowercase letters, digits, and
underscores, and have at most 32 characters. Choice keys use the same pattern with a
24-character limit. Validation rejects the host-reserved IDs `approve`, `commit`,
`reject`, `feedback`, `coder_prompt`, `coder_model`, `wait`, `epic_launch_mode`, and
`capacity`. It also rejects the YAML 1.1 words `y`, `n`, `yes`, `no`, `on`, `off`,
`true`, `false`, and `null` as both decision IDs and choice keys. Questions are one line
of at most 120 characters. Choice labels and `why` are one line of at most 100
characters. Do not restate the choice key, or a `Yes:`/`No:` prefix, at the start of its
label; the label states the consequence. There is no authored `kind` field: the presence
of `choices` selects the kind.

A `> [!decision] <id>` block marks the true branch of a toggle; `= no` marks its false
branch. A choice block must use `= <key>`. Unknown IDs or branches fail validation. The
ID is the first word after the marker, and the line has a branch only when `=` directly
follows the ID. Any other text on the header line is prose and is ignored. Prettier
joins a header with its first body line, so `> [!decision] grouping = pane` on its own
line and `> [!decision] grouping = pane Group bindings by pane.` mean the same thing,
and a toggle header joined to prose that contains `=` still names only its ID. Fenced
examples are ignored. An unmentioned decision produces a warning, so reference each
decision in the prose or a callout. Decisions do not conditionally schedule epic phases:
`phases[].when` is reserved and rejected.

Decisions ride the gate inputs to durable answers. ACE renders a Decisions panel above
the verdict, Telegram renders a decision keyboard, and the CLI takes
`-D/--decide ID=VALUE` (repeatable) with a decision card on every approval. To override
a default on a pending gate at the wire level, use the declared `decision_<id>` field
with `sase gate answer`:

```bash
# Replace REQUEST_ID with the pending tale gate's ID.
sase gate answer -k plan -i REQUEST_ID -o approve -o commit \
  --set decision_grouping=mode
```

For an epic, use `-k epic_plan -o approve`. Omitted inputs use the effective defaults.
Conflicting values across selected options fail before acceptance. Feedback carries
changed values into the replan as provisional choices; it does not approve the plan.

Archive fields: on approval, SASE writes each `decisions.<id>.answer` plus
`decided_by: reviewer|agent|auto` and, for non-auto approvals,
`decided_via: tui|telegram|mobile|cli` into the durable plan. Do not author those system
fields in a new proposal. Stamping is idempotent, and re-stamping different values is an
error; retry paths re-stamp from the recorded gate response. Committed plans are
validated in Archived mode, which is as strict as authoring mode but also allows these
system-written answer fields.

Decision definitions are frozen when the gate is created. In-gate edits can change
prose, but changing anything under `decisions:` is refused with an invitation to change
answers in the Decisions panel or send feedback to change the questions. Changing the
decision set requires a new proposal. Clients that submit a review revision are also
checked against the displayed revision; a stale revision fails before execution.

A memory decision is a toggle with `memory: [<selector>, ...]`. Selectors use the
[memory-read forms](../memory/memory.md#audited-reads): a note, a web, or a
`web:keyword` strand. They must resolve, and separate decisions cannot cover the same
resolved memory file. Use `default: false` for a proposed memory change the human has
not requested and that does not correct a false claim. A `default: true` memory decision
needs one quote of 3–300 characters: `requested` from human-authored text, or `corrects`
copied verbatim from the note's current text, naming a claim that is false or misleading
or that the plan's own work makes so. Never carry both; `requested` wins when the user
asked. Memory decisions cannot carry `why` or `choices`.

SASE verifies `requested` against the original human-typed launch prompt, human plan
feedback, or human free-text question answers in the planner's chain. Generated macro
text, model replies, selected option labels, auto-approval, and records without
authorship provenance do not establish that request. It verifies `corrects` against the
current raw text of the memory files that decision covers. Provenance is `asked` or
`correction` when the quote matches, `quote_not_found` or `claim_not_found` when it does
not, and `inherited` when an epic already authorized the same note. An unverified quote
makes the effective default false; agent-context validation and proposal reject an
authored true default without a verified quote. Validation outside an agent defers quote
verification to proposal. An agent cannot turn a memory decision on unless its effective
default is already true. Feedback about a memory decision remains provisional. See
[launch authorship](../../prompt.md#launch-authorship) and the
[gate protocol](../automation/notification-gates.md#plan-decisions).

When a plan-launched agent later commits, the host finalizer checks memory notes against
the accepted memory decisions, including decisions inherited from the agent's epic. A
note that no accepted decision covers still lands. The finalizer records a warning,
`memory_change_uncovered`, naming each uncovered path and the plan. Agents that were not
launched from a plan are not checked. If the guard cannot resolve the plan, the diff, or
the binding, it records nothing and the commit still lands. Generated root instruction
files (`AGENTS.md` and the provider shims) and `sase/memory/README.md` count as
uncovered only when that same declaration changes no covered memory note.

## Related

- [Plans](plans.md)
- [Plan commands](plan-cli.md)
