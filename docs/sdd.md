# Spec-Driven Development (SDD)

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
  workspace preparation. Monthly directories live directly at document roots; legacy
  single-root layouts remain readable for compatibility.

Use `sase repo path plans` or `sase repo path beads` to print those resolved roots, or
`sase repo path research --ensure` to materialize and print the research root. Launched
agents receive `SASE_SDD_DIR` and per-kind `SASE_SDD_*_DIR` variables, so prompts and
hooks should use those variables or repo resolvers instead of assuming `sdd/` is
relative to the checkout.

Project and user configuration cannot override this selection. See
[SDD Storage](sdd_storage.md) for the provider contract, sidecar-repo convention, setup
guidance, and offline/push behavior.

For built-in bare-git projects, SASE creates or refreshes the generated SDD guide files
automatically. Target an existing project with its `+<project>`
[project tag](macros.md#project-tags); first-use `#git:<project>` initialization (which
creates a new project and keeps its `#git:` spelling) includes them in the initial
commit; existing bare-repo registration, `#git` materialization, and `sase repo open`
commit and push an `Initialize SDD` init commit when the generated files are missing or
stale. First SDD writes, plan archiving, and `sase bead init` also refresh the generated
files before writing project-local SDD content.

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
bead, so a proposal from `sase-5.2` becomes `sase-5.2.1`, while the next child proposed
by the `sase-5` land agent becomes `sase-5.4` after phases `.1` through `.3`, and a
task-worker proposal from `sase-iq` becomes `sase-iq.1`. Agents with no bead association
at all continue to create top-level epics.

When `sase plan propose` submits a plan for approval, it touches the project's
`~/.sase/projects/<project>/artifacts/.ace_refresh_pulse` so any running sase's TUI
flips the agent into the tier-aware `TALE` or `EPIC` pending-review status immediately
rather than waiting for the next auto-refresh tick. Legacy or unreadable-tier plans use
the `PLAN` fallback. The pulse file is consumed by the inotify-based artifact watcher
and is harmless when no TUI is open.

Humans can approve the pending proposal from sase's TUI or from the CLI. `sase plan`
lists pending PlanApproval notifications, recent approvals, and inferred rejected
archived proposals. `sase plan approve <name>` defaults to a tale; an epic-authored plan
requires an explicit `--kind epic` or `--kind tale` to prevent an accidental downgrade.
The command can also directly approve an archived or scratch plan with no live gate;
`--dry-run` previews it and `--project` supplies explicit project context. Approving an
already-approved plan relaunches a failed, killed, or never-launched coder and refuses
one that is running or finished. The selected target schema is validated before the
response, SDD copy, or notification dismissal, and failures leave the proposal pending.

Tale approval promotes the plan and launches its coder through the agent runner. Every
epic approval surface — sase's TUI, the CLI, Telegram, or a bare gate response — instead
hands `sase bead work <plan-file> --yes-to-all` to a durable supervisor, because
launching an epic's phases is itself a long-running command that must outlive the
approving process.

The preferred form is a [monitor](monitors.md) turn under the planner's own agent
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
[CLI](cli.md#work-tracking-and-planning) for the resolution ladder and format details.

### Q&A Sections

If the agent asks clarifying questions during planning (via the `/sase_questions`
skill), the Q&A exchange is appended to the prompt archive document so the full context
of planning decisions is preserved.

Multi-round Q&A is rendered as a single merged `### Questions and Answers` section with
monotonic `Q1..QN` numbering across all rounds (a second round of questions continues at
the next free number rather than restarting at `Q1`). The section is wrapped in exactly
one `%macros_enabled` pair regardless of round count, and follow-up writes strip any
prior Q&A block (including legacy duplicate blocks from older runs) before re-emitting
the merged section. When a round carries a global note the "last non-empty wins" rule
applies — a later round's note replaces the earlier one, but an empty later note
preserves the earlier value.

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

- **PROMPT:**
  [prompts/202605/example.md](https://github.com/sase-org/sase--agents/blob/main/prompts/202605/example.md)
- **PARENT:**
  [202605/parent_epic.md](https://github.com/sase-org/sase--plans/blob/main/202605/parent_epic.md)
- **BEAD:**
  [sase-ai.8](https://github.com/sase-org/sase--beads/blob/main/pages/sase-ai/sase-ai.8.md)
- **AGENTS:**
  - [bbugyi200.athena.sase-8k.6](https://github.com/sase-org/sase--agents/blob/main/agents/bbugyi200.athena.sase-8k.6/README.md)
- **COMMITS:**
  - [699456a](https://github.com/sase-org/sase/commit/699456a521e25e0aaa38f4e289db38e71a6488a6)
    — fix(macro): canonicalize workflow project identity

# Plan: Example
```

The prompt names its plan:

```markdown
---
create_time: 2026-07-21 12:00:00
---

- **PLAN:**
  [202605/example.md](https://github.com/sase-org/sase--plans/blob/main/202605/example.md)
- **AGENTS:**
  - [bbugyi200.athena.sase-8k.6](https://github.com/sase-org/sase--agents/blob/main/agents/bbugyi200.athena.sase-8k.6/README.md)
- **ARTIFACTS:**
  - [diagram.png](../../artifacts/202605/ab12cd34ef56-diagram.png)

Original prompt text with
[@~/Downloads/diagram.png](../../artifacts/202605/ab12cd34ef56-diagram.png).
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
[SDD Storage](sdd_storage.md#concurrency-and-recovery)).

A plan's parent is recorded in the `PARENT` bullet. The historical `parent:` frontmatter
property is deprecated: it remains accepted so already-committed plans still validate,
but it emits a deprecation warning and `sase plan links refresh --write` migrates it
into a `PARENT` bullet. Plans whose `parent:` value does not resolve to a real plan file
are reported rather than dropped.

Historical `plan:` and `prompt:` frontmatter values remain readable in both their
original plain-path form and their later inline-Markdown form. Ordinary reads, search,
validation, initialization, and upgrades do not rewrite them. A canonical bullet plus a
redundant legacy property is tolerated when both resolve to the same physical target;
conflicting, malformed, duplicate, wrong-kind, unsafe, or nonexistent-target links are
reported rather than guessed. Run `sase plan links repair` to preview missing or stale
bullets and both legacy encodings, then run `sase plan links repair --write` to install
canonical bullets and remove only the corresponding legacy property. Repair preserves
unrelated frontmatter and body content and is idempotent.

`sase plan links validate` checks a tale or epic's own `PROMPT` bullet is well-formed;
it no longer checks that a matching prompt file exists, since prompts live in the
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

### Plan Frontmatter Schema and Validation

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
while launch validation normalizes both to `medium` with a warning so legacy tales still
launch.

SASE-managed `create_time`, `status`, `bead`, `bead_id`, and `proposed_by` fields are
accepted but never required. A plan may also declare
[review decisions](#plan-decisions); their answers and review stamps are written by
SASE. A proposal may carry the transient `links:` authoring inlet: a list of typed
artifact relationships that `sase plan propose` validates, persists, and removes before
archiving; see
[Authoring links in a proposed plan](artifact_links.md#authoring-links-in-a-proposed-plan).
Historical plans with a deprecated `prompt` or `parent` property remain valid, but both
are intentionally omitted from canonical schema and authoring output because new links
use the Markdown header block; `parent` additionally reports a deprecation warning
pointing at the `PARENT` bullet. Epics may also carry the SASE-managed `parent_bead`
field. Other unknown fields are errors. A plan must start with valid, closed YAML
frontmatter and contain a non-empty Markdown body.

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

### Plan Decisions

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
auto-approved plan with decisions posts one quiet receipt.

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
characters. There is no authored `kind` field: the presence of `choices` selects the
kind.

A `> [!decision] <id>` block marks the true branch of a toggle; `= no` marks its false
branch. A choice block must use `= <key>`. Unknown IDs or branches fail validation.
Fenced examples are ignored. An unmentioned decision produces a warning, so reference
each decision in the prose or a callout. Decisions do not conditionally schedule epic
phases: `phases[].when` is reserved and rejected.

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
[memory-read forms](memory.md#audited-reads): a note, a web, or a `web:keyword` strand.
They must resolve, and separate decisions cannot cover the same resolved memory file.
Use `default: false` for a proposed memory change the human has not requested. A
`default: true` memory decision needs a `requested` quote of 3–300 characters from
human-authored text; memory decisions cannot carry `why` or `choices`.

SASE verifies that quote against the original human-typed launch prompt, human plan
feedback, or human free-text question answers in the planner's chain. Generated macro
text, model replies, selected option labels, auto-approval, and records without
authorship provenance do not establish that request. An unverified request makes the
effective default false; agent-context validation and proposal reject an authored true
default without a verified quote. Validation outside an agent defers quote verification
to proposal. An agent cannot turn a memory decision on unless its effective default is
already true. Feedback about a memory decision remains provisional. See
[launch authorship](prompt.md#launch-authorship) and the
[gate protocol](notifications.md#plan-decisions).

When a plan-launched agent later commits, the host finalizer checks memory notes against
the accepted memory decisions, including decisions inherited from the agent's epic. A
note that no accepted decision covers still lands. The finalizer records a warning,
`memory_change_uncovered`, naming each uncovered path and the plan. Agents that were not
launched from a plan are not checked. If the guard cannot resolve the plan, the diff, or
the binding, it records nothing and the commit still lands. Generated root instruction
files (`AGENTS.md` and the provider shims) and `sase/memory/README.md` count as
uncovered only when that same declaration changes no covered memory note.

### Committed Plan Validation Cutover

Plans committed under a `YYYYMM` directory at or after `202608` must pass the complete
tier-specific frontmatter schema. SASE applies this gate before its SDD writers archive
or commit a plan, and CI runs `just validate-committed-plans` against the checked-out
plans sidecar. The sweep reports diagnostics for every plan in one run and fails if any
error is present.

Month directories before `202608` retain the legacy compatibility check: each direct
`YYYYMM/*.md` plan must declare a valid `tier: tale|epic`, but historical plans do not
need `goal` or structured epic phases. Exported or historical nested prompt snapshots
and historical root-level scratch files are not part of the committed-plan sweep.

## CLI

SDD's durable operations live primarily on the repo and plan command groups; executable
epic handoff uses the bead command group:

| Command                              | Purpose                                                                                                           |
| ------------------------------------ | ----------------------------------------------------------------------------------------------------------------- |
| `sase repo init`                     | Initialize configured sidecars, generated guides, config, and the repository ignore rule                          |
| `sase init repo`                     | Alias for `sase repo init`                                                                                        |
| `sase repo path REPO`                | Print a primary or sidecar path; `-e/--ensure` materializes the selected sidecar                                  |
| `sase plan links [list]`             | Print each prompt/plan artifact link and whether its reverse link is intact                                       |
| `sase plan links refresh`            | Preview header-block reconciliation; `-w/--write` applies, `-P/--plan REF` scopes, `-j/--json` reports            |
| `sase plan links repair`             | Preview canonical link migration; add `-w/--write` to update unambiguous pairs                                    |
| `sase plan links validate`           | Validate links; `-j/--json`, `-q/--quiet`, and `-W/--show-warnings` tune output                                   |
| `sase plan search`                   | Search or browse tale, epic, prompt, and document-sidecar (for example research) artifacts                        |
| `sase plan show [TARGET]`            | Resolve any plan reference form and render it; `-f/--format` picks full/compact/json/raw                          |
| `sase plan validate`                 | Validate by authored tier; `-e/--explain`, `-j/--json`, and `-q/--quiet` tune output                              |
| `sase bead work TARGET [TARGET ...]` | Validate, archive, link, and launch epic plans or bead targets in order; `-n/--dry-run` previews without mutation |

The link subcommands accept `-p/--path`, which may point at an SDD root or a project
root. Bare `sase plan links` defaults to `sase plan links list`. Validation no longer
checks that a plan has a paired prompt file or that a `PROMPT` bullet's target exists —
prompts live in the agents-sidecar archive and are validated separately by
`sase agent prompts validate`. `sase plan links validate` only checks a plan's own
metadata and `PROMPT` bullet: frontmatter parses, `tier` is valid, the header block
parses in its canonical form (`header-invalid` otherwise), `PARENT` resolves to a real
plan file, and the `PROMPT` bullet (when present) uses the correct link kind and
canonical placement; these are all errors unless explicitly allowlisted for legacy data.

The `PARENT` check is scoped to what the current workspace owns. Plans are published to
the store asynchronously, so a phase plan can land before the epic plan its `PARENT`
points at, and every workspace holding that snapshot would otherwise fail on a file none
of its agents wrote or can produce. An unresolvable `PARENT` is therefore a
`parent-missing-target` error only when the plans checkout reports local changes to the
referencing plan — the case the current agent can actually fix — and a
`parent-unpublished` warning when that plan is already published and merely waiting on
its parent to land. A plan tree that is not a usable git checkout stays strict, and
`sase plan links repair` reports both codes so the condition is never silent.

`sase plan links validate` hides warning-severity issues from its text output by default
— the summary line still reports the warning count and appends
`(use --show-warnings to display)` so they remain discoverable without scrolling through
noise on the happy path. Pass `-W/--show-warnings` to print each warning. JSON mode
(`-j/--json`) and exit codes are unaffected by `-W`.

For a repository whose own `sase/sase.yml` sets `is_sase_managed: true`, the
`sase repo init` command materializes the provider-selected store. On GitHub it finds or
creates every enabled configured sidecar, deriving `<owner>/<repo>--<role>` for unpinned
roles such as plans and research and honoring explicit repository pins. It writes each
repository's deterministic README and infographic asset, pushes generated drift, and
only then records the split store. Provider errors fail setup instead of falling back to
local storage. Missing or false markers make the command and `--check` successful no-ops
before provider work; invalid local configuration fails safely. `sase init repo` exposes
the same flow and the same `-c/--check`, `-d/--diff`, and `-C/--no-commit` flags; both
act on the repository containing the current directory.

Before explicit initialization creates a missing GitHub sidecar, it asks a default-no
question naming the role, repository, visibility, and host. Only `y` or `yes` approves.
Blank input, any other answer, EOF, interruption, and non-interactive stdin cancel with
a nonzero exit before repository or local-state mutations. An existing remote sidecar
connects without this creation prompt. `--check` remains offline and non-interactive,
and neither bare `sase init --yes` nor its generic initializer approval authorizes
repository creation.

Keep conceptual details here in `docs/sdd.md`; generated guides are safe to overwrite,
so do not put hand-maintained conceptual prose in those README files. Reserved roles and
the shipped `research` presentation preset pair their generated README with an
illustrated directory map, while other document sidecars receive only their
deterministic description-based README.

Bare-git projects normally do not need a manual `sase repo init`: SASE runs the same
generated-file refresh during repository setup, workspace materialization, and the first
in-tree SDD write. The explicit command remains useful for manual refreshes and
`--check` drift audits.

## Bead Integration

`sase bead work <plan-file>` initializes the [bead issue tracker](beads.md)
automatically when its resolved store does not have one yet:

- **In-tree mode**: Beads are stored in `sdd/beads/` at the project root.
- **Local mode**: Beads are stored in `.sase/sdd/beads/`; `.sase/sdd/` is a standalone
  git repo.
- **Separate-repo mode**: Beads are stored in `.sase/sdd/beads/` inside the sidecar
  checkout.
- **Split sidecar mode**: Schema-3 projects store beads at the root of the active
  workspace's `--beads` repository, materialized on demand. Schema-2 projects retain
  `beads/` in the `--plans` clone.

Plan-like beads carry a `tier` value:

- `plan` for ordinary non-epic implementation plans.
- `epic` for executable multi-phase plans.

Standalone task beads live in the same store and carry no tier or parent. Their creation
and launch paths are plan-free: agents use `/sase_new_task` first, then use
`sase bead create --type 'task(bug)' --title "Follow up" --size small -w "Independent follow-up that does not belong on the current epic" -f location=src/foo.py -f repro='fails on retry'`
only for an independent follow-up. See the
[standalone task workflow](beads.md#standalone-task-workflow) for ready-state triage and
one-worker launch behavior. The generic bead update command currently accepts design
metadata on a task, but task launch does not consume it as an SDD plan.

For larger efforts, epic files carry `bead_id` and `tier: epic` in their frontmatter.
The command validates the epic, archives it into the resolved plans store, creates the
epic and phase beads, wires the authored dependencies, commits the `bead_id` link, and
launches the shared bead-work schedule. Each phase bead's ID is written as a structured
`SASE_BEAD=<id>` commit footer, creating a traceable chain from epic to phase to commit
and its generated bead page. A stale `bead_id` whose bead is missing is reported with a
remedy instead of silently creating a second epic.

For smaller plans, commit messages include a `SASE_PLAN=<path>` tag pointing back to the
plan file. The path is relative to the repository that owns the plan:
`sdd/plans/<YYYYMM>/<name>.md` for in-tree storage and `plans/<YYYYMM>/<name>.md` for
local or legacy separate-repo stores. In a split `--plans` repository, it is
`<YYYYMM>/<name>.md`. Agents can also build paths from the kind-specific root, for
example `$SASE_SDD_PLANS_DIR/{YYYYMM}/{name}.md`.

## Configuration

```yaml
sdd:
  bead_refresh:
    mode: background
    ttl_seconds: 120
  repo:
    name: "" # optional sidecar repo override for providers that support it
  push_after_commit: async
```

| Option                         | Type        | Default      | Description                                                                                                                                                                                                                                                  |
| ------------------------------ | ----------- | ------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `sdd.bead_refresh.mode`        | string      | `background` | `background` launches TTL-gated command refreshes, `blocking` pulls before commands, and `off` disables remote refreshes, including the axe bead-wait refresh job and the refresh step in the waiting runner's fallback. Local dependency rechecks continue. |
| `sdd.bead_refresh.ttl_seconds` | float       | `120`        | Minimum seconds between successful command-triggered background integrations.                                                                                                                                                                                |
| `sdd.repo.name`                | string      | `""`         | Optional sidecar repo override for providers that support `separate_repo`; accepts `name` or `owner/name`. For GitHub, empty checks only `<owner>/<repo>--sdd`; set `sdd.repo.name` to use another repo such as `sdd` or `owner/sdd`.                        |
| `sdd.push_after_commit`        | bool/string | `async`      | Sidecar-repository push behavior after SDD commits: `async`, `true`, or `false`.                                                                                                                                                                             |

Storage selection is not configurable. The workspace provider owns it. Retired
`sdd.storage` and `sdd.version_controlled` keys are ignored and reported by
`sase doctor` for cleanup.

See [`configuration.md`](configuration.md) for the full configuration reference and
[SDD Storage](sdd_storage.md) for mode behavior.

## Multi-Workspace Behavior

SDD artifact placement follows provider policy. With `in_tree`, bead commands use the
current checkout's `sdd/beads/` store. With `separate_repo`, commands first require a
usable provider sidecar and then use the active workspace's `.sase/sdd/` clone. With
`sidecar_repos`, each workspace auto-clones `--plans` at `sase/repos/plans`; schema-3
records materialize `--beads` at `sase/repos/beads` on demand, in `sase bead` and in the
agent-launch bead claim, while schema-2 records keep bead state under
`sase/repos/plans/beads`. Initialization also prepares every configured document sidecar
at `sase/repos/<role>` in its current workspace; other workspaces clone lazy roles,
including beads, when explicitly ensured. Providerless local storage uses the primary
workspace. Numbered sibling stores are not merged; coordinate shared state through the
normal VCS sync path. Prefer `sase repo path plans`, `sase repo path beads`,
`sase repo path <document-role>`, or the `SASE_SDD_*_DIR` variables over hard-coded
relative paths. Numbered-workspace sidecar clones borrow Git objects from the primary
workspace's clone of the same sidecar when one exists; see
[Network Git Operations](sdd_storage.md#network-git-operations) for clone retries and
timeouts.
