---
title: Plans
description: Spec-Driven Development storage, artifacts, and plan lifecycle in SASE.
---

# Plans

Plans record work proposals and decisions before SASE starts the work they describe.

SDD is sase's system for persisting the intent behind agent work. When an agent submits
a plan for approval, SDD keeps the approved planning artifact in the plans store and
links it to the canonical prompt archive in the agents sidecar, creating a traceable
chain from intent to execution. In this guide, "plan-like artifact" means a tale or
epic.

SDD is sase's system for persisting the intent behind agent work. When an agent submits
a plan for approval, SDD keeps the approved planning artifact in the plans store and
links it to the canonical prompt archive in the agents sidecar, creating a traceable
chain from intent to execution. In this guide, "plan-like artifact" means a tale or
epic.

## Why SDD Exists

Agent plans are ephemeral by default -- they live in a single session's context window
and vanish when the session ends. SDD fixes this by writing plans and linked prompt
archives to disk as first-class artifacts:

- **Prompts** preserve a durable primary body and, when available, the final
  preprocessed prompt SASE handed to the provider in the agents sidecar's
  `prompts/<YYYYMM>/` archive. For an approved plan, the primary body is the
  dry-expanded planning snapshot; for an ordinary commit publication, it is the
  pre-expansion Macro.
- **Tales** record ordinary approved implementation plans, so decomposition decisions
  are queryable after the fact.
- **Epics** record executable multi-phase plans that can be handed to `sase bead work`.
- **Research** records exploratory findings, prior art, options, critiques, and
  recommendations that inform later work.
- **Beads** provide structured issue tracking that links SDD artifacts to execution via
  plan-like bead tiers and phase or epic IDs in `SASE_BEAD=` commit footers.

Together, these create an audit trail from prompt archives to planning artifacts and
supporting context. Tales and epics can link into the bead hierarchy and phase commits;
research notes preserve the longer-lived context those plans depend on.

## Provider-Owned Storage

The workspace provider selects an initial policy; a materialized store record supplies
the concrete layout:

- `in_tree` stores artifacts under the checkout's `sdd/` directory and commits them with
  code changes.
- `local` is the fallback for providerless projects and stores artifacts at the primary
  workspace's `.sase/sdd/`.
- `separate_repo` stores artifacts in a workspace-local `.sase/sdd/` clone backed by a
  provider-materialized sidecar repo.
- `sidecar_repos` stores plans in an auto-cloned `--plans` repo and every configured
  document role in its own sidecar. A schema-3 record stores bead state at the root of
  its dedicated `--beads` clone; a schema-2 compatibility record keeps `beads/` under
  `--plans`. Initialization prepares configured sidecars in its current workspace; later
  workspaces clone the beads sidecar and lazy document roles on demand instead of during
  workspace preparation. Monthly directories live directly at document roots;
  single-root layouts remain readable for compatibility.

Use `sase repo path plans` or `sase repo path beads` to print those resolved roots, or
`sase repo path research --ensure` to materialize and print the research root. Launched
agents receive `SASE_SDD_DIR` and per-kind `SASE_SDD_*_DIR` variables, so prompts and
hooks should use those variables or repo resolvers instead of assuming `sdd/` is
relative to the checkout.

Project and user configuration cannot override this selection. See
[SDD Storage](../../contribute/sdd-storage.md) for the provider contract, sidecar-repo
convention, setup guidance, and offline/push behavior.

For built-in bare-git projects, SASE creates or refreshes the generated SDD guide files
automatically. Target an existing project with its `+<project>`
[project tag](../macros/reference-syntax.md#project-tags); first-use `#git:<project>`
initialization (which creates a new project and keeps its `#git:` spelling) includes
them in the initial commit; existing bare-repo registration, `#git` materialization, and
`sase repo open` commit and push an `Initialize SDD` init commit when the generated
files are missing or stale. First SDD writes, plan archiving, and `sase bead init` also
refresh the generated files before writing project-local SDD content.

Research notes live under `research/{YYYYMM}/` inside the effective SDD root. A
`#research` macro (defined in user or project config -- the packaged default was
removed) conventionally tells the agent to create a new markdown file in the current
month directory; SASE does not write research files automatically.

## How SDD Works

### Prompt Archive Publication

SASE has two prompt-publication paths, and their ordering matters:

1. **Approved plan:** while handling approval, SASE first dry-expands the planner
   prompt, publishes the plan-named archive entry, and then writes the tale or hands the
   epic to `sase bead work`. Dry expansion resolves macros, strips prompt directives,
   and inlines workflow `prompt_part` content without executing pre- or post-steps.
2. **Agent-backed commit:** after the primary commit succeeds, the commit workflow
   publishes the run's `raw_macros.md` inline. Project and configured macro aliases have
   already been resolved, but macros have not been expanded. A plan-backed entry uses
   the plan slug; an entry without a plan uses the publishing agent's global lane name.

That plan snapshot or pre-expansion Macro becomes the archive body. SASE turns staged
`@...` references into durable links when possible.

### Artifact Persistence

The approved plan artifact is:

1. Annotated with a `create_time` frontmatter field
2. Given a required `tier: tale|epic` frontmatter value and written to
   `<plans-root>/{YYYYMM}/{plan_name}.md`, where `{YYYYMM}` is derived from the current
   date. Its `PROMPT` header links to the canonical prompt archive entry in the agents
   sidecar, `prompts/{YYYYMM}/{plan_name}.md`, when that prompt has been published.

For tales, the agent runner publishes the prompt before it writes and commits the
promoted plan; these are ordered operations, not one atomic cross-repository
transaction. For epics, the runner likewise publishes the planner prompt first, while
the canonical `sase bead work <plan-file>` command owns archiving and linking the plan
itself. This keeps host approval and the finishing planner agent from writing the same
plan concurrently.

Plans and research notes are organized into `YYYYMM` subdirectories (for example,
`202603/`) based on the creation date. Canonical prompts are organized in the agents
sidecar under `prompts/<YYYYMM>/`; copied prompt-linked bytes live in that sidecar's
content-addressed `files/objects/sha256/<hex-prefix>/<sha256>` object store. Plan
discovery remains limited to `<plans-root>/<YYYYMM>/*.md`. Resolve the plans root with
`sase repo path plans` or `SASE_SDD_PLANS_DIR`; historical plans-sidecar prompt
directories, top-level `prompts/`, and `specs/` aliases remain readable for
compatibility.

Planning artifacts may also carry a `status` field (set to `done` when work completes)
and a `bead_id` field linking to the bead issue tracker. For an epic,
`sase bead work <plan-file>` writes `bead_id` after it creates the epic and phase beads.
Re-running the command sees that link and resumes the existing epic instead of creating
duplicates.

When an epic is proposed from a bead-work phase agent, SASE records that phase's ID as
the managed `parent_bead`; an epic proposed by the land agent records the current epic's
ID instead. An agent working a task bead records that task's ID, so a proposed epic
becomes a child of the task. Approving the proposal creates a child epic under that
bead, so a proposal from `<phase-bead-id>` becomes `<phase-bead-id>.1`, while a child
proposed by a land agent becomes the next numbered child after the authored phases, and
a task-worker proposal becomes `<task-bead-id>.1`. Agents with no bead association at
all continue to create top-level epics.

When `sase plan propose` submits a plan for approval, it touches the project's
`~/.sase/projects/<project>/artifacts/.ace_refresh_pulse` so any running sase's TUI
flips the agent into the tier-aware `TALE` or `EPIC` pending-review status immediately
rather than waiting for the next auto-refresh tick. Plans with a missing or unreadable
tier use the `PLAN` fallback. The pulse file is consumed by the inotify-based artifact
watcher and is harmless when no TUI is open.

`sase plan propose` formats the plan with prettier and re-validates the formatted copy
before archiving it. It then formats that copy a second time, matching archival, and
re-validates again. If either pass would change the plan's validity or its decision
callouts, propose exits non-zero and proposes nothing: the scratch file, the archive,
and the running agent are left untouched, so the agent can fix the plan and propose
again. SASE protects intraword underscores (`snake_case`) from Prettier's emphasis
parsing so a second pass cannot rewrite identifiers into `snake*case`.

Humans can approve the pending proposal from sase's TUI or from the CLI. `sase plan`
lists pending PlanApproval notifications, recent approvals, and inferred rejected
archived proposals. `sase plan approve <name>` defaults to a tale; an epic-authored plan
requires an explicit `--kind epic` or `--kind tale` to prevent an accidental downgrade.
The command can also directly approve an archived or scratch plan with no live gate;
`--dry-run` previews it and `--project` supplies explicit project context. When
`--project` is omitted, a proposal's frontmatter `project` field supplies the project.
Approving an already-approved plan relaunches a failed, killed, or never-launched coder
and refuses one that is running or finished. The selected target schema is validated
before the response, SDD copy, or notification dismissal, and failures leave the
proposal pending.

For a saved epic file with no live approval gate, use `sase bead work <plan-file>`. The
direct `sase plan approve` route does not launch gateless epics. An explicit
`--kind tale` instead runs that plan as a single tale after tale-schema validation.

Tale approval promotes the plan and launches its coder through the agent runner. Every
epic approval surface — sase's TUI, the CLI, Telegram, or a bare gate response — instead
hands `sase bead work <plan-file> --yes-to-all` to a durable supervisor, because
launching an epic's phases is itself a long-running command that must outlive the
approving process.

The preferred form is a [monitor](../../monitors.md) turn under the planner's own agent
session, labeled `Epic launch · <plan>`. The monitor turn reads `EPIC APPROVED` while
`sase bead work` runs and uses its configured `EPIC CREATED` label after any terminal
outcome—even failure, timeout, stop, or loss. Treat the monitor's state, bucket, exit
code, and output as the result. Only a successful launch attempts to back-fill the epic
ID; when that metadata lands, the planner row itself moves to `EPIC CREATED`, and
otherwise it remains `EPIC APPROVED`. No follow-up agent is recorded — `sase bead work`
launches the phase agents itself — and the monitor takes a zero workspace claim, since
the launch runs in the project's primary workspace rather than the planner's. If the
planner's agent session cannot be resolved (a very old artifacts layout, or a wiped
agent), the launch falls back to an unattributed command proc with the same command and
label rather than silently dropping the approval. Other monitor-start errors fail the
approval rather than selecting that fallback.

Either way the launch is durable: it survives the approving process, and normal command
success or failure emits the epic-completion notification. Inspect a monitor-backed
launch with `sase monitor list` / `sase monitor show <id> --follow`; the unattributed
proc fallback appears in every default `sase proc list` and Procs-tab scope and streams
with `sase proc show <id> --follow`. A durable manual fallback is
`sase proc run --session none --label 'Epic launch · <plan>' -- sase bead work <plan> --yes-to-all`.
If the approval host cannot resolve or submit the launch, approval fails loudly with a
direct `sase bead work <plan> --yes-to-all` resume command (plus applicable metadata
flags), not the wrapper above, instead of falling back to an invisible planner-side
subprocess. On the proc fallback path, which has no monitor row to relabel, the planner
remains `EPIC APPROVED` until successful metadata back-fill makes the created epic
known.

`--kind approve` runs the coder without committing an SDD plan, while `--kind commit`
records the approved plan in SDD without launching a coder. `--wait` accepts
comma-separated agent names and `bead=<id>` entries; tale approvals apply that wait to
the coder, and epic approvals apply it to the launched phase agents.
`sase plan reject <name>` writes the same no-feedback rejection response as the TUI,
then attempts to dismiss and user-kill the matching planner row when it can be found.

To recall prior planning artifacts, `sase plan search [QUERY]` searches plans, research,
and historical prompt snapshots in the resolved SDD store (the `repo` source, surfaced
first) plus the machine-local `~/.sase/plans/` archive. Use `sase agent prompts list`
and `sase agent prompts show` for the canonical agents-sidecar prompt archive. The query
is optional — omit it to browse and filter with repeatable
`--kind tale|epic|prompt|<document-role>` (any configured document sidecar, such as
`research`), `--status`, `--source`, and `--since`/`--until` date bounds. Results are
ranked (relevance with a query, recency without; `--sort` overrides), capped by
`--limit` (default 20, `0` for unlimited), and render as colored `compact`/`full` output
or as agent-friendly `json`/`markdown` via `--format`.

Once you know which plan you want, `sase plan show [TARGET]` resolves it — a path, a
`plan:` reference, a pending-approval selector, a bare slug or `<shard>/<slug>`, or a
bead id — to exactly one plan and renders it as a colored, section-structured detail
view matching the PLAN lane in sase's TUI, with `compact`, `json`, and byte-faithful
`raw` output alongside the default `full` view. See
[CLI](../../cli.md#work-tracking-and-planning) for the resolution ladder and format
details.

### Q&A Sections

If the agent asks clarifying questions during planning (via the `/sase_questions`
skill), the Q&A exchange is appended to the prompt archive document so the full context
of planning decisions is preserved.

Multi-round Q&A is rendered as a single merged `### Questions and Answers` section with
monotonic `Q1..QN` numbering across all rounds (a second round of questions continues at
the next free number rather than restarting at `Q1`). The section is wrapped in exactly
one `%macros_enabled` pair regardless of round count, and follow-up writes strip any
existing Q&A blocks (including duplicates) before re-emitting the merged section. When a
round carries a global note the "last non-empty wins" rule applies — a later round's
note replaces the earlier one, but an empty later note preserves the earlier value.

### Artifact Links

Archived prompts and plan-like artifacts link to each other through ordinary Markdown
bullets, so GitHub renders the counterpart as a clickable link. A plan opens with a
**header block**: a contiguous run of those bullets, in the fixed order `PROMPT`,
`PARENT`, `BEAD`, `AGENTS`, `ARTIFACTS`, `COMMITS`, that carries the plan's full
provenance.

```markdown
---
tier: tale
title: Example
goal: Demonstrate the plan-side layout.
size: small
---

- **PROMPT:** `<prompt-path>`
- **PARENT:** `<parent-plan-path>`
- **BEAD:** `<bead-page-url>`
- **AGENTS:** `<agent-log-url>`
- **COMMITS:** `<commit-url>`

# Plan: Example
```

The prompt names its plan:

```markdown
---
create_time: 2026-07-21 12:00:00
---

- **PLAN:** `<plan-path>`
- **AGENTS:** `<agent-log-url>`
- **ARTIFACTS:** `<artifact-path>`

Original prompt text may refer to a local artifact with `@~/Downloads/diagram.png`.
```

When YAML frontmatter exists, its opening `---` remains at byte zero. The header block
is the first Markdown body element after the closing delimiter, followed by exactly one
blank line before the authored content (including an H1). Without frontmatter, the block
starts at the first file line. `PROMPT` and `PLAN` name the linked counterpart.

The text inside `[]` is the storage-layout-aware stable label. For current `PROMPT` and
`PLAN` links, the href inside `()` is normally a hosted cross-repository URL: plans
point at the agents sidecar's `prompts/<YYYYMM>/`, and prompts point back at the plans
sidecar's `<YYYYMM>/*.md` file. Historical file-relative prompt-to-plan and
plan-to-prompt hrefs remain valid and readable during migration.

#### Header Block Sections

| Section     | Shape               | Destination                                                              |
| ----------- | ------------------- | ------------------------------------------------------------------------ |
| `PLAN`      | one link (prompts)  | hosted plan URL in the plans sidecar, else a historical relative href    |
| `PROMPT`    | one link (plans)    | hosted prompt URL in the agents sidecar, else a historical relative href |
| `PARENT`    | one link            | hosted plan URL in the plans sidecar, else a file-relative href          |
| `BEAD`      | one link or label   | hosted bead page when available and not disproved by a readable store    |
| `AGENTS`    | ordered sub-bullets | hosted agent README URL in the agents sidecar, else an unlinked name     |
| `ARTIFACTS` | ordered sub-bullets | hosted repository blobs or agents-sidecar file-object links              |
| `COMMITS`   | ordered sub-bullets | hosted commit URL in the primary repository, else an unlinked SHA        |

Sub-bullets are indented exactly two spaces and deterministically ordered: agents by
name, artifacts by rendered prompt order, and commits by full SHA (or by the short-SHA
label of an unlinked commit), so every writer produces the same order. Commit
sub-bullets show the seven-character short SHA as link text and append `— <subject>`. A
section with nothing to show is omitted entirely — an empty `- **AGENTS:**` header is
never rendered — and a list longer than the shared render cap ends with a visible
`… and N more` sub-bullet instead of being silently truncated. Rendered bullets are
wrap-tolerant: prettier may fold a long commit sub-bullet onto continuation lines, and
parsing joins those lines back into one logical bullet.

SASE owns the header block; do not author it by hand. A bullet that deviates from the
canonical form above is a validation error (`header-invalid`), not a style choice: a
link-shaped section (`PLAN`, `PROMPT`, `PARENT`, `BEAD`) must be a bolded key followed
by exactly one Markdown link and nothing else — `BEAD` alone may instead carry a bare
unlinked label, as the table above notes — and a list-shaped section (`AGENTS`,
`ARTIFACTS`, `COMMITS`) must be a bare bolded key with at least one indented sub-bullet
and no inline content. Repeating a section, or carrying both `PLAN` and `PROMPT` in one
document, is the same error.

The diagnostic names the offending path and the parser's reason, and the same
`header-invalid` code is raised at every validation surface: `sase plan validate`,
`sase plan links validate`, `sase plan links refresh`, the plan approval gate, and
`sase bead work`. `sase bead work` validates the source file before it archives
anything, so a malformed block fails with that diagnostic and leaves no partially
written destination file behind.

`BEAD` is a projection of durable state. It comes from the plan's managed `bead_id` (or
historical `bead`) frontmatter and is rebuilt on every refresh. It links when a hosted
page URL can be formed and a readable bead store does not show the ID to be missing.
`sase plan propose` stamps that managed `bead` field when a tale is proposed by a phase
agent, land agent, or task-bead worker with an active bead association. If the resolved
store is readable and confirms that the bead is absent, or if no hosted page URL is
available, it remains an unlinked label so historical IDs do not become dead links. If
the store cannot be read, refresh preserves a candidate hosted link rather than
stripping potentially valid links during a transient failure.

`AGENTS` and `COMMITS` are derived from `SASE_PLAN=` / `SASE_AGENT=` commit footers and
agent artifact metadata, then merged into the rows the plan already carries. A refresh
only sees the commits and agent artifacts available where it runs, so it adds the rows
it derives and updates the text and link of rows it derives again, but it never removes
a row. A refresh that derives nothing leaves both sections untouched, and two machines
that refresh in either order converge on the same rows. Agent rows are matched by name;
commit rows are matched by the full SHA in their link, or by short-SHA label when
unlinked, and a linked row replaces an unlinked row with the same label. Because rows
are never pruned, correcting a wrong footer or artifact does not remove a row that an
earlier refresh already wrote.

Both sources are normalized to the **sase agent**, so each sase agent is listed exactly
once: a plan touched by `pc--code` and `pc--plan` shows a single `pc` row linked to the
session page, never the member and its session as two agents. Solo agents are listed
exactly as before. The row's link is taken from the concrete turn when any source knew
one, otherwise from the destination recorded in the commit footer, and it degrades to an
unlinked label rather than guessing a URL. Bead-page agent rows follow the same rule,
and their commit counts are the sase agent's commits. An epic plan's sections roll up
its own associations with those of every descendant plan reachable through `PARENT`.
`sase plan links refresh` reconciles the whole tree (dry run by default; `--write` to
apply, `--plan <ref>` to scope to one plan), and each primary commit refreshes the plan
it names on a best-effort basis — a plans-store failure never blocks the code commit.

Refreshes on different machines can still edit the same plan concurrently. When SASE
rebases a plans store (sidecar integration, or a bare-git project's commit rebase) and a
month-sharded plan file conflicts only in its `AGENTS` and `COMMITS` rows, SASE resolves
the conflict itself: it writes the union of both sides' rows, keeps the local side's
text for a row both sides carry, and stages the file. A difference in frontmatter,
`PROMPT`, `PARENT`, `BEAD`, or the authored body, an unparseable header, or a
modify/delete conflict is never merged; it is left to SASE's normal conflict handling,
which for sidecar integration restores the pre-rebase state (see
[SDD Storage](../../contribute/sdd-storage.md#concurrency-and-recovery)).

A plan's parent is recorded in the `PARENT` bullet. The `parent:` frontmatter property
remains accepted for existing committed plans, with a deprecation warning;
`sase plan links refresh --write` moves it into a `PARENT` bullet. Plans whose `parent:`
value does not resolve to a real plan file are reported rather than dropped.

`plan:` and `prompt:` values in plain-path or inline-Markdown form remain readable.
Ordinary reads, search, validation, and initialization do not rewrite them. A canonical
bullet and matching property may coexist; conflicting, malformed, duplicate, wrong-kind,
unsafe, or unresolved links are reported rather than guessed. Run
`sase plan links repair --write` to install canonical bullets and remove matching
properties. See the
[plan-frontmatter migration note](../upgrading/work-units.md#plan-frontmatter).

`sase plan links validate` checks a tale or epic's own `PROMPT` bullet is well-formed;
it does not check that a matching prompt file exists, since prompts live in the
agents-sidecar archive rather than the plans tree. Research notes are durable SDD
context, but they are not part of the prompt-plan link validator.

### Model Field

Plan files may carry an optional top-level `model:` field in YAML frontmatter to record
the model the work should run under. The value uses the same syntax `%model` accepts: a
bare known model name (e.g. `opus`), a provider-qualified id (e.g. `codex/gpt-6.1-sol`),
or a configured local alias (e.g. `#pro`).

```yaml
# plans/202605/example.md
tier: tale
model: opus
```

For an epic, the top-level `model` selects the final land-agent model. Per-phase models
live only in the structured `phases[].model` frontmatter entries; body annotations are
not interpreted:

```yaml
tier: epic
title: Model-routed rollout
goal: Complete the rollout and verify it end to end
model: claude/opus
phases:
  - id: implementation
    title: Implement the rollout
    depends_on: []
    size: medium
  - id: exercise
    title: Exercise the completed rollout
    depends_on: [implementation]
    size: xsmall
```

On Epic approval, SASE deterministically copies the top-level model to the epic plan
bead and each phase's model and size to its phase bead. `xsmall`, `small`, and `medium`
phases implement directly with `@xsmall`, `@small`, and `@medium`, respectively. Only
`large` and `xlarge` phases receive `#plan`, after their work reference, and use
`@large` and `@xlarge`. Each size alias is a direct selector with its own shipped
target; there is no second-alias hop. Set an explicit phase `model` only when the user's
prompt requested that model; the explicit model is valid at every size and always wins
over size-derived routing without changing whether the phase receives `#plan`. When the
top-level model is omitted, the land agent uses `llm_provider.epic_lander_model`
(shipped default `@large`) below `bead.big_epic_phase_threshold` and
`llm_provider.big_epic_lander_model` (shipped default `@xlarge`) at or above the
threshold (default `5`). These are independent scalar fields, each with its own shipped
default; neither falls back through the other or through a `default` alias. An explicit
top-level land model or direct field override still wins. The approval preview and
emitted launch prompt use these same rules. Routing counts every authored phase,
including already-closed phases when an epic resumes, so the selected lander field stays
stable throughout the epic.

Choose `xsmall` only for the very simplest tasks that need almost no reasoning, such as
launching SASE agents purely to observe their output while testing a SASE agent feature.
Choose `small` for focused work that can be implemented directly. Choose `medium` for
substantial work that can still be implemented directly from its phase description.
Choose `large` for work that needs a separate planning handoff and may itself justify an
epic plan. Choose `xlarge` rarely: it admits the task is too large to plan effectively
alone, or deliberately defers planning part of a feature until other parts are
implemented.

<a id="plan-frontmatter-schema-and-validation"></a> Moved to
[Plan format](plan-format.md#plan-frontmatter-schema-and-validation).
<a id="plan-decisions"></a> Moved to [Plan format](plan-format.md#plan-decisions).

### Committed Plan Validation Cutover

Plans committed under a `YYYYMM` directory at or after `202608` must pass the complete
tier-specific frontmatter schema. SASE applies this gate before its SDD writers archive
or commit a plan, and CI runs `just validate-committed-plans` against the checked-out
plans sidecar. The sweep reports diagnostics for every plan in one run and fails if any
error is present.

For month directories before `202608`, the compatibility check requires: each direct
`YYYYMM/*.md` plan must declare a valid `tier: tale|epic`, but historical plans do not
need `goal` or structured epic phases. Exported or historical nested prompt snapshots
and historical root-level scratch files are not part of the committed-plan sweep.

## Related

- [Plan format](plan-format.md)
- [Plan commands](plan-cli.md)
- [Plan configuration](plan-execution.md)
- [Beads](beads.md)
