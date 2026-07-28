# Spec-Driven Development (SDD)

SDD is sase's system for persisting the intent behind agent work. When an agent submits a plan for approval, SDD can
capture both the expanded prompt snapshot and the approved planning artifact, creating a traceable chain from intent to
execution. In this guide, "plan-like artifact" means a tale or epic.

## Why SDD Exists

Agent plans are ephemeral by default -- they live in a single session's context window and vanish when the session ends.
SDD fixes this by writing prompt snapshots and plans to disk as first-class artifacts:

- **Prompts** record the full expanded prompt the agent received, so the "why" behind the work is preserved.
- **Tales** record ordinary approved implementation plans, so decomposition decisions are queryable after the fact.
- **Epics** record executable multi-phase plans that can be handed to `sase bead work`.
- **Research** records exploratory findings, prior art, options, critiques, and recommendations that inform later work.
- **Beads** provide structured issue tracking that links SDD artifacts to execution via plan-like bead tiers and phase
  IDs in commit messages.

Together, these create an audit trail from prompt snapshots to planning artifacts and supporting context. Tales and
epics can link into the bead hierarchy and phase commits; research notes preserve the longer-lived context those plans
depend on.

## Provider-Owned Storage

The workspace provider selects an initial policy; a materialized store record supplies the concrete layout:

- `in_tree` stores artifacts under the checkout's `sdd/` directory and commits them with code changes.
- `local` is the fallback for providerless projects and stores artifacts at the primary workspace's `.sase/sdd/`.
- `separate_repo` stores artifacts in a workspace-local `.sase/sdd/` clone backed by a provider-materialized sidecar
  repo.
- `sidecar_repos` stores plans and beads in an auto-cloned `--plans` repo. Research uses the config-declared `research`
  role, which derives each project's own `--research` repo unless a `repo:` pin says otherwise. Initialization prepares
  configured sidecars in its current workspace; later workspaces clone research on demand. Monthly directories live
  directly at each sidecar root; legacy single-root layouts remain readable for compatibility.

Use `sase repo path plans` to print the plans root, or `sase repo path research --ensure` to materialize and print the
research root. Launched agents receive `SASE_SDD_DIR` and per-kind `SASE_SDD_*_DIR` variables, so prompts and hooks
should use those variables or repo resolvers instead of assuming `sdd/` is relative to the checkout.

Project and user configuration cannot override this selection. See [SDD Storage](sdd_storage.md) for the provider
contract, sidecar-repo convention, setup guidance, and offline/push behavior.

For built-in bare-git projects, SASE creates or refreshes the generated SDD guide files automatically. First-use
`#git:<project>` initialization includes them in the initial commit; existing bare-repo registration, `#git`
materialization, and `sase repo open` commit and push an `Initialize SDD` init commit when the generated files are
missing or stale. First SDD writes, plan archiving, and `sase bead init` also refresh the generated files before writing
project-local SDD content.

Research notes live under `research/{YYYYMM}/` inside the effective SDD root. A `#research` xprompt (defined in user or
project config -- the packaged default was removed) conventionally tells the agent to create a new markdown file in the
current month directory; SASE does not write research files automatically.

## How SDD Works

### Prompt Generation

When a submitted plan is accepted, SDD generates a prompt snapshot by:

1. Expanding all `#xprompt` references in the original prompt
2. Stripping `%directives` (`%model`, `%id`, `%wait`, etc.)
3. Dry-expanding embedded workflow `prompt_part` content (renders templates without executing pre/post steps)

The result is a clean, self-contained document showing exactly what the agent was asked to do.

### Artifact Persistence

The approved plan artifact is:

1. Annotated with a `create_time` frontmatter field
2. Given a required `tier: tale|epic` frontmatter value and written to `<plans-root>/{YYYYMM}/{plan_name}.md`, where
   `{YYYYMM}` is derived from the current date. Its prompt snapshot is written beside it at
   `<plans-root>/{YYYYMM}/prompts/{plan_name}.md`.

For tales, the agent runner promotes the plan and prompt snapshot together. For epics, the runner writes and commits
only the prompt snapshot; the canonical `sase bead work <plan-file>` command owns archiving and linking the plan itself.
This keeps host approval and the finishing planner agent from writing the same plan concurrently.

Prompt snapshots, plans, and research notes are organized into `YYYYMM` subdirectories (for example, `202603/`) based on
the creation date. Prompt snapshots are nested under each plan month at `<plans-root>/<YYYYMM>/prompts/`. This keeps
paired artifacts together while plan discovery remains limited to `<plans-root>/<YYYYMM>/*.md`. Resolve the plans root
with `sase repo path plans` or `SASE_SDD_PLANS_DIR`; historical top-level `prompts/` and `specs/` aliases remain
readable for compatibility.

Planning artifacts may also carry a `status` field (set to `done` when work completes) and a `bead_id` field linking to
the bead issue tracker. For an epic, `sase bead work <plan-file>` writes `bead_id` after it creates the epic and phase
beads. Re-running the command sees that link and resumes the existing epic instead of creating duplicates.

When an epic is proposed from a bead-work phase agent, SASE also records that phase's ID as the managed `parent_bead`;
an epic proposed by the land agent records the current epic's ID instead. Approving the proposal creates a child epic
under that bead, so a proposal from `sase-5.2` becomes `sase-5.2.1`, while the next child proposed by the `sase-5` land
agent becomes `sase-5.4` after phases `.1` through `.3`. Agents outside bead work have no association and continue to
create top-level epics.

When `sase plan propose` submits a plan for approval, it touches `~/.sase/.ace_refresh_pulse` so any running ACE TUI
flips the agent into the tier-aware `TALE` or `EPIC` pending-review status immediately rather than waiting for the next
auto-refresh tick. Legacy or unreadable-tier plans use the `PLAN` fallback. The pulse file is consumed by the
inotify-based artifact watcher and is harmless when no TUI is open.

Humans can approve the pending proposal from ACE or from the CLI. `sase plan` lists pending PlanApproval notifications,
recent approvals, and inferred rejected archived proposals. `sase plan approve <id-prefix>` defaults to the tier
authored in the plan; `--kind tale|epic` explicitly overrides it. The selected target schema is validated before the
response, SDD copy, or notification dismissal, and failures leave the proposal pending.

Tale approval promotes the plan and launches its coder through the agent runner. Every epic approval surface — ACE, the
CLI, Telegram, or a bare gate response — instead submits one global `detached` task whose command is
`sase bead work <plan-file> --yes-to-all`. No interactive session owns that task, so it survives the approving process,
appears in every default `sase task list` and Tasks-tab scope, is streamable with `sase task show <id> --follow`, and
still emits the epic-completion notification. The equivalent hand-run form is
`sase task run --detached --label 'Epic launch · <plan>' -- sase bead work <plan> --yes-to-all`. If the approval host
cannot resolve or submit the launch, approval fails loudly with that resume command instead of falling back to an
invisible planner-side subprocess. After a successful handoff, the planner finishes with `EPIC APPROVED`.

`--kind approve` runs the coder without committing an SDD plan, while `--kind commit` records the approved plan in SDD
without launching a coder. `sase plan reject <id-prefix>` writes the same no-feedback rejection response as the TUI,
then attempts to dismiss and user-kill the matching planner row when it can be found.

To recall prior artifacts, `sase plan search [QUERY]` searches plans, prompt snapshots, and research in the resolved SDD
store (the `repo` source, surfaced first) plus the machine-local `~/.sase/plans/` archive. The query is optional — omit
it to browse and filter with `--kind tale|epic|prompt|research`, `--status`, `--source`, and `--since`/`--until` date
bounds. Results are ranked (relevance with a query, recency without) and render as colored `compact`/`full` output or as
agent-friendly `json`/`markdown` via `--format`.

### Q&A Sections

If the agent asks clarifying questions during planning (via the `/sase_questions` skill), the Q&A exchange is appended
to the prompt snapshot so the full context of planning decisions is preserved.

Multi-round Q&A is rendered as a single merged `### Questions and Answers` section with monotonic `Q1..QN` numbering
across all rounds (a second round of questions continues at the next free number rather than restarting at `Q1`). The
section is wrapped in exactly one `%xprompts_enabled` pair regardless of round count, and follow-up writes strip any
prior Q&A block (including legacy duplicate blocks from older runs) before re-emitting the merged section. When a round
carries a global note the "last non-empty wins" rule applies — a later round's note replaces the earlier one, but an
empty later note preserves the earlier value.

### Artifact Links

Prompt snapshots and plan-like artifacts link to each other through ordinary Markdown bullets, so GitHub renders the
counterpart as a clickable link. A plan opens with a **header block**: a contiguous run of those bullets, in the fixed
order `PROMPT`, `PARENT`, `AGENTS`, `COMMITS`, that carries the plan's full provenance.

```markdown
---
tier: tale
title: Example
goal: Demonstrate the plan-side layout.
---

- **PROMPT:** [sdd/plans/202605/prompts/example.md](prompts/example.md)
- **PARENT:** [202605/parent_epic.md](https://github.com/sase-org/sase--plans/blob/main/202605/parent_epic.md)
- **AGENTS:**
  - [bbugyi200.athena.sase-8k.6](https://github.com/sase-org/sase--agents/blob/main/agents/bbugyi200.athena.sase-8k.6/README.md)
- **COMMITS:**
  - [699456a](https://github.com/sase-org/sase/commit/699456a521e25e0aaa38f4e289db38e71a6488a6) — fix(xprompt):
    canonicalize workflow project identity

# Plan: Example
```

The prompt names its plan:

```markdown
---
create_time: 2026-07-21 12:00:00
---

- **PLAN:** [../sdd/plans/202605/example.md](../example.md)

Original prompt text.
```

When YAML frontmatter exists, its opening `---` remains at byte zero. The header block is the first Markdown body
element after the closing delimiter, followed by exactly one blank line before the authored content (including an H1).
Without frontmatter, the block starts at the first file line. `PROMPT` and `PLAN` name the linked counterpart.

The text inside `[]` is the storage-layout-aware stable SDD label. For `PROMPT` and `PLAN` the href inside `()` is
relative to the physical file containing the bullet: prompt-to-plan hrefs ascend from `prompts/`, while plan-to-prompt
hrefs descend into it. Local `.sase/sdd` labels retain that prefix. In a flat `--plans` sidecar, the equivalent bullets
are `- **PLAN:** [../202605/example.md](../example.md)` in the prompt and
`- **PROMPT:** [202605/prompts/example.md](prompts/example.md)` in the plan.

#### Header Block Sections

| Section   | Shape               | Destination                                                          |
| --------- | ------------------- | -------------------------------------------------------------------- |
| `PLAN`    | one link (prompts)  | file-relative href inside the plans store                            |
| `PROMPT`  | one link (plans)    | file-relative href inside the plans store                            |
| `PARENT`  | one link            | hosted plan URL in the plans sidecar, else a file-relative href      |
| `AGENTS`  | ordered sub-bullets | hosted agent README URL in the agents sidecar, else an unlinked name |
| `COMMITS` | ordered sub-bullets | hosted commit URL in the primary repository, else an unlinked SHA    |

Sub-bullets are indented exactly two spaces and deterministically ordered: agents by global name, commits by commit time
then SHA. Commit sub-bullets show the seven-character short SHA as link text and append `— <subject>`. A section with
nothing to show is omitted entirely — an empty `- **AGENTS:**` header is never rendered — and a list longer than the
shared render cap ends with a visible `… and N more` sub-bullet instead of being silently truncated. Rendered bullets
are wrap-tolerant: prettier may fold a long commit sub-bullet onto continuation lines, and parsing joins those lines
back into one logical bullet.

`AGENTS` and `COMMITS` are a projection of durable state, never an accumulator. They are re-derived from `SASE_PLAN=` /
`SASE_AGENT=` commit footers and agent artifact metadata on every refresh, so a stale or wrong entry disappears once its
source is corrected. An epic plan's sections roll up its own associations with those of every descendant plan reachable
through `PARENT`. `sase plan links refresh` reconciles the whole tree (dry run by default; `--write` to apply,
`--plan <ref>` to scope to one plan), and each primary commit refreshes the plan it names on a best-effort basis — a
plans-store failure never blocks the code commit.

A plan's parent is recorded in the `PARENT` bullet. The historical `parent:` frontmatter property is deprecated: it
remains accepted so already-committed plans still validate, but it emits a deprecation warning and
`sase plan links refresh --write` migrates it into a `PARENT` bullet. Plans whose `parent:` value does not resolve to a
real plan file are reported rather than dropped.

Historical `plan:` and `prompt:` frontmatter values remain readable in both their original plain-path form and their
later inline-Markdown form. Ordinary reads, search, validation, initialization, and upgrades do not rewrite them. A
canonical bullet plus a redundant legacy property is tolerated when both resolve to the same physical target;
conflicting, malformed, duplicate, wrong-kind, unsafe, or nonexistent-target links are reported rather than guessed. Run
`sase plan links repair` to preview missing or stale bullets and both legacy encodings, then run
`sase plan links repair --write` to install canonical bullets and remove only the corresponding legacy property. Repair
preserves unrelated frontmatter and body content and is idempotent.

`sase plan links validate` checks these bidirectional links for prompts, tales, and epics. It treats unpaired historical
files as warnings by default and as errors with `--strict`. Research notes are durable SDD context, but they are not
part of the prompt-plan link validator.

### Model Field

Plan files may carry an optional top-level `model:` field in YAML frontmatter to record the model the work should run
under. The value uses the same syntax `%model` accepts: a bare known model name (e.g. `opus`), a provider-qualified id
(e.g. `codex/gpt-5.6-sol`), or a configured local alias (e.g. `#pro`).

```yaml
# plans/202605/example.md
tier: tale
model: opus
```

For an epic, the top-level `model` selects the final land-agent model. Per-phase models live only in the structured
`phases[].model` frontmatter entries; body annotations are not interpreted:

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

On Epic approval, SASE deterministically copies the top-level model to the epic plan bead and each phase's model and
size to its phase bead. `xsmall`, `small`, and `medium` phases implement directly with `@xsmall_phase_worker`,
`@small_phase_worker`, and `@medium_phase_worker`, respectively. Only `large` and `xlarge` phases receive `#plan`, after
their work reference, and use `@large_phase_worker` and `@xlarge_phase_worker`. The size aliases fall back to
`@cheaper`, `@cheap`, `@default@high`, `@smart`, and `@smartest` for `xsmall`, `small`, `medium`, `large`, and `xlarge`
respectively. Set an explicit phase `model` only when the user's prompt requested that model; the explicit model is
valid at every size and always wins over size-derived routing without changing whether the phase receives `#plan`. The
standalone `@cheapest` provider fallback is available for explicit use but is not selected automatically. When the
top-level model is omitted, the land agent uses `@epic_lander` below `bead.big_epic_phase_threshold` and
`@big_epic_lander` at or above the threshold (default `5`). The normal role falls back to `@default`; the
threshold-selected role falls back independently to provider-aware `@smartest`. An explicit top-level land model or
direct role-alias override still wins. The approval preview and emitted launch prompt use these same rules. Routing
counts every authored phase, including already-closed phases when an epic resumes, so the selected lander role stays
stable throughout the epic.

Choose `xsmall` only for the very simplest tasks that need almost no reasoning, such as launching SASE agents purely to
observe their output while testing a SASE agent feature. Choose `small` for focused work that can be implemented
directly. Choose `medium` for substantial work that can still be implemented directly from its phase description. Choose
`large` for work that needs a separate planning handoff and may itself justify an epic plan. Choose `xlarge` rarely: it
admits the task is too large to plan effectively alone, or deliberately defers planning part of a feature until other
parts are implemented.

### Plan Frontmatter Schema and Validation

Run `sase plan validate PLAN_FILE` while authoring a plan. The command selects the schema from the plan's required
top-level `tier: tale` or `tier: epic` property; the former `-t/--tier` option has been removed. Validation is hermetic:
the command accepts any readable UTF-8 path and does not require `SASE_AGENT`, `SASE_ARTIFACTS_DIR`, or a registered
project context. It reports all problems in one pass with stable diagnostic codes, field paths, and best-effort line
numbers.

Every tale and epic requires these authored fields:

| Field   | Required | Rule                                                               |
| ------- | -------- | ------------------------------------------------------------------ |
| `tier`  | yes      | `tale` or `epic`; selects the validation schema                    |
| `title` | yes      | Non-empty human-readable plan title                                |
| `goal`  | yes      | Non-empty description of the outcome the plan is intended to reach |
| `model` | no       | Non-empty model value using the same syntax as `%model`            |

SASE-managed `create_time`, `status`, `bead`, and `bead_id` fields are accepted but never required. Historical plans
with a deprecated `prompt` or `parent` property remain valid, but both are intentionally omitted from canonical schema
and authoring output because new links use the Markdown header block; `parent` additionally reports a deprecation
warning pointing at the `PARENT` bullet. Epics may also carry the SASE-managed `parent_bead` field. Unknown fields are
errors. A plan must start with valid, closed YAML frontmatter and contain a non-empty Markdown body.

Epics additionally require an ordered, non-empty `phases` list. Optional `changespec` and integer `bug_id` metadata may
be supplied; `bug_id` requires `changespec`. The epic-only `parent_bead` associates an approved plan with the bead under
which SASE creates its child epic. Each phase requires a unique slug `id`, a non-empty `title`, a `depends_on` list, and
`size: xsmall | small | medium | large | xlarge`. Dependencies may only name earlier phases, cannot repeat, and cannot
refer to the phase itself. Optional phase fields are `description` and `model`. Only set a phase model when the user's
prompt requested one; for a phase that only exercises or observes a SASE agent feature and does no consequential work,
use `size: xsmall` instead of a cheap model override.

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

Epic-only fields on a tale produce warnings because they are inert when a human downgrades an epic-authored plan. All
other schema violations are errors. Human failures always include the authoritative expected-schema table and a minimal
valid example. Add `-e/--explain` to print tier-specific authoring guidance before the result; in JSON mode the same
guidance is included as an `explanation` field. `-q/--quiet` suppresses a successful human summary, but an explicitly
requested explanation is still printed.

If `tier` is missing or is not `tale` or `epic`, validation fails with an actionable hint and omits the explanation
because no authored schema can be selected. To keep reporting the other problems in the file, the implementation uses
the tale schema as a diagnostic fallback. Consequently, JSON reports `"tier": "tale"` and the expected tale schema in
this error case; that value does **not** mean SASE inferred a tale. The tier diagnostic still fails the command. JSON
stays on stdout while the tier hint is written to stderr. Otherwise `-j/--json` returns `schema_version`, `ok`, the
authored `tier`, `path`, the complete diagnostics list, and the expected schema. Exit status is 0 for valid plans, 1 for
validation failures, and 2 for command-usage errors.

### Committed Plan Validation Cutover

Plans committed under a `YYYYMM` directory at or after `202608` must pass the complete tier-specific frontmatter schema.
SASE applies this gate before its SDD writers archive or commit a plan, and CI runs `just validate-committed-plans`
against the checked-out plans sidecar. The sweep reports diagnostics for every plan in one run and fails if any error is
present.

Month directories before `202608` retain the legacy compatibility check: each direct `YYYYMM/*.md` plan must declare a
valid `tier: tale|epic`, but historical plans do not need `goal` or structured epic phases. Nested prompt snapshots and
historical root-level scratch files are not part of the committed-plan sweep.

## CLI

SDD's durable operations live primarily on the repo and plan command groups; executable epic handoff uses the bead
command group:

| Command                    | Purpose                                                                                        |
| -------------------------- | ---------------------------------------------------------------------------------------------- |
| `sase repo init`           | Initialize configured sidecars, generated guides, config, and the repository ignore rule       |
| `sase init repo`           | Alias for `sase repo init`                                                                     |
| `sase repo path REPO`      | Print a primary or sidecar path; `-e/--ensure` materializes the selected sidecar               |
| `sase plan links [list]`   | Print each prompt/plan artifact link and whether its reverse link is intact                    |
| `sase plan links refresh`  | Preview header-block reconciliation; `-w/--write` applies it, `-P/--plan REF` scopes it        |
| `sase plan links repair`   | Preview canonical link migration; add `-w/--write` to update unambiguous pairs                 |
| `sase plan links validate` | Validate links; `-j/--json`, `-q/--quiet`, `-s/--strict`, and `-W/--show-warnings` tune output |
| `sase plan search`         | Search or browse tale, epic, prompt, and research artifacts                                    |
| `sase plan validate`       | Validate by authored tier; `-e/--explain`, `-j/--json`, and `-q/--quiet` tune output           |
| `sase bead work PLAN_FILE` | Validate, archive, link, and launch an epic plan; `-n/--dry-run` previews without mutation     |

The link subcommands accept `-p/--path`, which may point at an SDD root or a project root. Bare `sase plan links`
defaults to `sase plan links list`. Validation treats unpaired or ambiguous historical files as warnings by default and
promotes them to errors with `--strict`; parse errors, missing targets, wrong link kinds, and broken reverse links are
errors unless explicitly allowlisted for legacy data.

`sase plan links validate` hides warning-severity issues from its text output by default — the summary line still
reports the warning count and appends `(use --show-warnings to display)` so they remain discoverable without scrolling
through noise on the happy path. Pass `-W/--show-warnings` to print each warning, or `--strict` to promote warnings to
errors before filtering. JSON mode (`-j/--json`) and exit codes are unaffected by `-W`.

For a repository whose own `sase/sase.yml` sets `is_sase_managed: true`, the `sase repo init` command materializes the
provider-selected store. On GitHub it finds or creates every enabled configured sidecar, deriving
`<owner>/<repo>--<role>` for unpinned roles such as plans and research and honoring explicit repository pins. It writes
each repository's deterministic README and infographic asset, pushes generated drift, and only then records the split
store. Provider errors fail setup instead of falling back to local storage. Missing or false markers make the command
and `--check` successful no-ops before provider work; invalid local configuration fails safely. `sase init repo` exposes
the same flow and check/path flags, and `--path` checks the target repository's marker.

Before explicit initialization creates a missing GitHub sidecar, it asks a default-no question naming the role,
repository, visibility, and host. Only `y` or `yes` approves. Blank input, any other answer, EOF, interruption, and
non-interactive stdin cancel with a nonzero exit before repository or local-state mutations. An existing remote sidecar
connects without this creation prompt. `--check` remains offline and non-interactive, and neither bare `sase init --yes`
nor its generic initializer approval authorizes repository creation.

Keep conceptual details here in `docs/sdd.md`; generated guides are safe to overwrite, so do not put hand-maintained
conceptual prose in those README files.

Bare-git projects normally do not need a manual `sase repo init`: SASE runs the same generated-file refresh during
repository setup, workspace materialization, and the first in-tree SDD write. The explicit command remains useful for
manual refreshes and `--check` drift audits.

## Bead Integration

`sase bead work <plan-file>` initializes the [bead issue tracker](beads.md) automatically when its resolved store does
not have one yet:

- **In-tree mode**: Beads are stored in `sdd/beads/` at the project root.
- **Local mode**: Beads are stored in `.sase/sdd/beads/`; `.sase/sdd/` is a standalone git repo.
- **Separate-repo mode**: Beads are stored in `.sase/sdd/beads/` inside the sidecar checkout.
- **Split sidecar mode**: Beads are stored at `beads/` in the active workspace's auto-cloned `--plans` repository.

Plan-like beads carry a `tier` value:

- `plan` for ordinary non-epic implementation plans.
- `epic` for executable multi-phase plans.

For larger efforts, epic files carry `bead_id` and `tier: epic` in their frontmatter. The command validates the epic,
archives it into the resolved plans store, creates the epic and phase beads, wires the authored dependencies, commits
the `bead_id` link, and launches the shared bead-work schedule. Each phase bead's ID appears in commit messages,
creating a traceable chain from epic to phase to commit. A stale `bead_id` whose bead is missing is reported with a
remedy instead of silently creating a second epic.

For smaller plans, commit messages include a `SASE_PLAN=<path>` tag pointing back to the plan file. The path is relative
to the repository that owns the plan: `sdd/plans/<YYYYMM>/<name>.md` for in-tree storage and `plans/<YYYYMM>/<name>.md`
for local or legacy separate-repo stores. In a split `--plans` repository, it is `<YYYYMM>/<name>.md`. Agents can also
build paths from the kind-specific root, for example `$SASE_SDD_PLANS_DIR/{YYYYMM}/{name}.md`.

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

| Option                         | Type        | Default      | Description                                                                                                                                                                                                                                                   |
| ------------------------------ | ----------- | ------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `sdd.bead_refresh.mode`        | string      | `background` | `background` launches TTL-gated command refreshes, `blocking` pulls before commands, and `off` disables remote refreshes, including the axe bead-wait refresh chop and the refresh step in the waiting runner's fallback. Local dependency rechecks continue. |
| `sdd.bead_refresh.ttl_seconds` | float       | `120`        | Minimum seconds between successful command-triggered background integrations.                                                                                                                                                                                 |
| `sdd.repo.name`                | string      | `""`         | Optional sidecar repo override for providers that support `separate_repo`; accepts `name` or `owner/name`. For GitHub, empty checks only `<owner>/<repo>--sdd`; set `sdd.repo.name` to use another repo such as `sdd` or `owner/sdd`.                         |
| `sdd.push_after_commit`        | bool/string | `async`      | Sidecar-repository push behavior after SDD commits: `async`, `true`, or `false`.                                                                                                                                                                              |

Storage selection is not configurable. The workspace provider owns it. Retired `sdd.storage` and
`sdd.version_controlled` keys are ignored and reported by `sase doctor` for cleanup.

See [`configuration.md`](configuration.md) for the full configuration reference and [SDD Storage](sdd_storage.md) for
mode behavior.

## Multi-Workspace Behavior

SDD artifact placement follows provider policy. With `in_tree`, bead commands use the current checkout's `sdd/beads/`
store. With `separate_repo`, commands first require a usable provider sidecar and then use the active workspace's
`.sase/sdd/` clone. With `sidecar_repos`, each workspace auto-clones `--plans` at `sase/repos/plans` for plans and
beads. Initialization also prepares a configured `research` sidecar at `sase/repos/research` in its current workspace;
other workspaces clone it when explicitly ensured. Providerless local storage uses the primary workspace. Numbered
sibling stores are not merged; coordinate shared state through the normal VCS sync path. Prefer `sase repo path plans`,
`sase repo path research`, or the `SASE_SDD_*_DIR` variables over hard-coded relative paths.
