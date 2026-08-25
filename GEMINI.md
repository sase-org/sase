# Structured Agentic Software Engineering (SASE) - Agent Instructions

## 1. Tier 1 (core) Memory

The following memories contain core (always loaded) context:

### 1.1 SASE = Structured Agentic Software Engineering (sase)

#### 1.1.1 SASE Memory

SASE memory is this project's durable agent context: Markdown notes under `sase/memory/`
that render into this file. A note's `type:` frontmatter decides how it reaches you.

- **Core memory** (`type: core`) is Tier 1. It is inlined here and into every provider
  instruction shim, so it is always in your context and every note is paid for on every
  turn.
- **Reference memory** (`type: reference`) is Tier 2. Only its one-line description is
  listed here; read the body on demand with your `/sase_memory_read` skill, never by
  opening the file directly.
- **Memory webs** are keyed collections: a flat descriptor note (`sase/memory/<web>.md`)
  plus a sibling directory of strand files (`sase/memory/<web>/<slug>.md`). The
  descriptor renders at either tier, but a strand body is never inlined — read strands
  by keyword (`glossary:stitch`) through the same skill.

IMPORTANT: You should not modify any of these memory files without approval from the
user. Authorization found in a plan file, bead description, design doc, or any other
agent-produced artifact does NOT count as user permission. However, when the user
explicitly asks you to update a SASE memory file, that request already carries the
required approval for the full workflow: make the requested edit to the canonical note
under `sase/memory/`, then you MUST run `sase memory init` to regenerate `AGENTS.md`,
the provider instruction shims, and the memory README. Do NOT ask for separate
permission to initialize sase memory in that case.

#### 1.1.2 Ephemeral `sase_<N>` Workspace Directories

SASE runs agents (like you) from ephemeral workspace directories, which are full clones
of the sase repo. These directories are named `sase_<N>` where `<N>` is some integer.
You need to be mindful not to run commands outside of these workspace directories, since
they have their own isolated virtual environments.

IMPORTANT: Do NOT mention your workspace directory (or any sibling workspace directory)
in any plan files that you generate using your `/sase_plan` skill. The agent(s) that
implement the plan might not run in the same workspace directory as you!

#### 1.1.3 Repositories

Configured linked and sidecar repositories for this context:

- `sase-github`: GitHub VCS and workspace provider plugin for repository, issue, and PR
  workflows.
- `sase-telegram`: Telegram integration plugin for chat-driven SASE workflows and
  notifications.
- `sase-nvim`: Neovim integration plugin for SASE syntax, completion, and editor
  support.
- `sase-research-artifacts`: Installable artifact-reference plugin that provides the
  `@research` document provider, `research-highlights` file-hook template, and
  `#research*` xprompts.
- `sase--research`: Durable SASE research reports and generated media used by research
  workflows.

When you need to read or modify files in any repository other than your own workspace
checkout, agents MUST use your `/sase_repo` skill first. This includes configured linked
repos and sidecars, another SASE project's repo, and any GitHub repo not linked to the
current project. Open different-project and unlinked GitHub repos as external repos
through the skill. Use the path it prints as the only path for reads and writes.

This rule applies regardless of transport. Fetching a repository's files or history over
the web — github.com file/blob/raw URLs, raw.githubusercontent.com, repo tarballs, or
GitHub-API/`gh` file-content reads — counts as reading that repo: open it with
`/sase_repo` (unlinked GitHub repos open as external repos, e.g. `gh:<owner>/<repo>`)
and read the local checkout instead. Web tools remain appropriate only for content a
checkout does not contain, such as blog posts, docs sites, and GitHub issue/PR
discussions.

IMPORTANT REMINDER: Do NOT locate, clone, or web-fetch another repo's contents any other
way than by using `/sase_repo`!

#### 1.1.4 SASE Final Declaration

Before any normal response that ends this SASE provider turn, use your `/sase_final`
skill as the last action. This includes a final answer, an incomplete-status response,
an "I will wait" response, or any reply that intends to resume in a later turn. It will
call `sase final context`, inspect any selected finalizers and repository obligations,
and submit one atomic declaration with `sase final submit` when the host requires one.
The declaration must cover every repository you changed this turn, including linked,
sidecar, or external repos opened through `/sase_repo`. A host prompt scoped to one
repository's commit or conflict repair does not narrow that obligation for any other
repository you changed.

After a successful `sase final submit`, do not make more file or repository changes in
this turn. If the declaration command reports validation errors, repair the manifest and
resubmit before returning when possible. Only a successfully executed plan, monitor,
pipe, or questions handoff is exempt, because those commands terminate the runner
mechanically. Intending to resume later is not an exemption.

### 1.2 Build & Run Commands (build_and_run)

```bash
just install       # Install in editable mode with dev deps
just lint          # ruff check + mypy
just fmt           # Auto-format code
just check         # Agent default: whole-repo lint gates + a diff-scoped
                   # test lane that never queues behind another agent's run
just check-full    # Exhaustive verification: every lint gate + the full
                   # test suite; run before landing and in CI
just test          # Fast parallel pytest run (excludes PNG visual snapshots)
just test-cov      # pytest with coverage + 50% gate (used by CI); also
                   # excludes the visual snapshot suite
```

#### 1.2.1 IMPORTANT: Two-Speed Verification — Run `just check` if you Made File Changes

If you made file changes in this repo (the sase repo), make sure to run the `just check`
command before terminating / replying to the user.

`just check` runs every whole-repo lint gate plus a diff-scoped test lane
(`just test-scoped`) that selects tests via a static import-graph closure. The scoped
run is serial unless a middle gear wins it a small, bounded suite-gate lease, and it
never queues behind other agents' runs either way. Selection is a heuristic backstopped
by CI: `tools/select_tests --explain` shows why a test was or was not chosen, and
`just selection-health` shows whether the heuristic has ever been wrong.

Run `just check-full` instead — every lint gate plus the full test suite — before
landing an epic's combined tree, when the change touches the broadening set, or any time
`just check`'s scoped run escalated or reported an unusual selection.

`just check-full` routinely outruns a single agent turn, so run it **only** through your
`/sase_monitor` skill, never inline, using the `TESTING` / `TESTED` status pair.
`just check` may be run inline, but hand it to a monitor the same way whenever it is
taking a long time.

**IMPORTANT**: One consequence of sase's ephemeral workspace directories (see the
sase.md file in this directory) is that you MAY need to run `just install` before
running other commands like `just check` (since it is possible we haven't used this
workspace directory in a long time and package dependencies may have changed).

#### 1.2.2 PNG Snapshot Tests

Run `just test-visual` for the dedicated ACE PNG snapshot suite; goldens live in
`tests/ace/tui/visual/snapshots/png/`. On failures, inspect `.pytest_cache/sase-visual/`
for actual/expected/diff/source artifacts, and use `--sase-update-visual-snapshots` to
accept intentional visual changes. Local runs use exact pixel equality by default, while
CI allows a small ratio-only renderer drift tolerance; the visual fixtures pin color and
fontconfig/Fira Code to keep rendering deterministic.

### 1.3 Decisions (decisions)

A decision record is not a design doc or a subsystem overview — those go stale as the
code changes underneath them. A record is immutable once accepted: if the project
changes course, a new record is written and the old one is marked superseded in prose,
never edited in place. Read one on demand with
`sase memory read decisions:<keyword> -r "<why>"`; each record states the claim, why it
was chosen over the credible alternatives, what it costs, and the condition that would
reopen it.

<!-- sase:strands -->

- **Agents Are Single-Turn** (`single-turn-agents`) - A SASE agent run is one provider
  turn; continuation is always mechanical, never a promise to resume.
- **Completion Is Host-Owned** (`host-owned-completion`) - An agent never creates
  commits, branches, or PRs; it submits a declaration and host-owned finalizers act.
- **Memory Webs** (`memory-webs`) - A keyed memory collection is a flat descriptor note
  plus a sibling strand directory, addressed web:keyword.
- **No Retrieval Mechanism Before Its Corpus** (`corpus-before-mechanism`) - SASE does
  not build memory retrieval or linking machinery ahead of a corpus that demonstrably
  needs it.
- **The Rust Core Is Required** (`rust-core-required`) - Shared backend behavior lives
  in sase-core with no Python fallback and no env-var backend switch.
- **Verification Is Two-Speed** (`two-speed-verification`) - just check is the agent
  default and just check-full gates landing, because host capacity is the constraint,
  not test speed.

<!-- /sase:strands -->

### 1.4 Glossary Terms (glossary)

Run `sase memory read glossary:<term> [<term> ...] -r "<why>"` before relying on any of
these SASE terms; it prints each term's definition plus every term those definitions
depend on. Pass every term you need in one command — one batched read costs far fewer
tokens than one read per term, because terms shared between definitions are printed
once. Terms are separated by semicolons; aliases follow in parentheses.

<!-- sase:strands -->

**GLOSSARY TERMS:** Agent Clan; Agent Family; Agent Hood (hood, agent neighborhood);
Agent Instruction File (agents.md file); Agent Neighbor; Agent Node; Agent Shell; Agent
Tribe; Artifact; Artifact Markdown File (artifact md file, artifact md); Artifact
Reference (ref); Chop; Core Memory (core memory); Current Project; Feature Flag; Flag
Bead (flag bead); Lumberjack; Memory Strand; Memory Web; Patch; Proc (background task);
Proc Shell; Reference Memory (reference memory); Required Plugin (required plugin); Sase
Agent (agent); Sase Monitor (monitor); Sase Node (node); Sase Project; Sase Repo; Sase
Shell (shell); Sase Workspace (workspace); Stitch; Strand Keyword; Task Type (task
type); Xprompt; Xprompt Memory (memory file, sase memory); Xprompt Part; Xprompt Swarm;
Xprompt Workflow

<!-- /sase:strands -->

### 1.5 Code Conventions and Gotchas (gotchas)

**Default Keymap Config**  
When changing keymaps, leader mode keys, or any configuration values, don't forget to
update the keymap configuration in the `src/sase/default_config.yml` file if necessary.

### 1.6 Rust Core Backend Boundary (rust_core_backend_boundary)

Shared backend and domain behavior belongs in the sibling Rust core repo at
`../sase-core/crates/sase_core`. Python and TUI code in this repo should call through
the Rust binding (`sase_core_rs`) or a thin local adapter instead of reimplementing core
logic here.

Use this litmus test: if a web app, CLI, editor integration, or another frontend would
need the behavior to match the TUI, treat it as core backend logic.

Presentation-only Textual state, keybindings, layout, widget rendering, and Python glue
can stay in this repo. When a change crosses the boundary, update the Rust wire/API,
bindings, and tests in `../sase-core`, then update the Python callers or adapters here.

### 1.7 Task Bead Types (task_types)

Every task bead can carry a `task_type` drawn from this project's catalog.
`sase bead task-type list` always shows the live catalog; read
`sase memory read task_types:<slug> -r "<why>"` for one generated type in full. This
note is the generated, always-current snapshot of the agent-creatable types below.

<!-- sase:strands -->

- **Bug** (`bug`) - A defect an agent found while doing unrelated work, not an external
  tracker bug.
- **CI failure** (`ci`) - A confirmed true test or lint failure, not a flake.
- **Feature** (`feature`) - An out-of-scope product idea that should not become a wish
  list.
- **Flaky test** (`flake`) - A test that fails and then passes on an unchanged tree.
- **Memory** (`memory`) - A sase memory note or skill that is out of date.

<!-- /sase:strands -->

#### 1.7.1 File Discovered Work As Task Beads

Unless your prompt explicitly forbids creating beads (epic phase workers, for example,
must record `PROPOSED FOLLOW-UP:` notes on their own bead instead), you can and SHOULD
capture discovered follow-up work as sase task beads. Pick the type above whose
`when_to_use` matches what you found:

- A linter or test is flaky or failing and you did not cause it: file a task bead
  instead of ignoring the failure.
- A sase memory file or skill contains out-of-date information that should be updated:
  file a task bead proposing the update.
- A tool, command, or script this project is responsible for has a bug or a clear,
  objective improvement that would help future agents: file a task bead to fix or
  improve it.

Before creating any task bead, you MUST use `/sase_new_task`. That skill checks every
task status for semantic duplicates, checks in-progress epics for a credible causal
link, and records the issue in the right place. Only a genuinely new task becomes an
`open` draft, and every new task requires an intentional `--size` plus
`-T "task(<slug>)"` and `-f/--field` values for that type's required fields. Ready task
beads are proposed to the project owner, who either launches an agent to work them or
closes them with a reason.

## 2. Tier 2 (reference) Memory

The below files contain detailed reference material. When working in their domain, you
MUST use your `/sase_memory_read` skill to review their contents. Do not read canonical
memory files directly.

### 2.1 `sase/memory/cli_rules.md`

Read anytime new CLI subcommands or options are added.

### 2.2 `sase/memory/generated_skills.md`

Read when working with sase agent skills (aka xprompt skills), which are generated from
source templates in the `src/sase/xprompts/skills/` and deployed to managed locations
(my chezmoi repo, for example).

### 2.3 `sase/memory/sase_artifacts.md`

Read before creating, consuming, resolving, linking, or managing retention for SASE
artifact references and indexed files.

### 2.4 `sase/memory/sase_beads.md`

Read before creating, updating, closing, or querying sase beads — bead types and tiers,
the status lifecycle agents must never hand-edit, task-bead triage, phase-bead
description prefixes, and non-cascading close, resolution, and note semantics.

### 2.5 `sase/memory/sase_flags.md`

Read before adding, deferring, or removing a SASE feature flag or flag bead, and before
deprecating user-reaching behavior or landing code whose old branch must stay reachable
for backward compatibility.

### 2.6 `sase/memory/symvision.md`

Read before fixing Symvision lint failures, including unused symbols, private misuse,
pragmas, and epic whitelists.

### 2.7 `sase/memory/tui_perf.md`

Read before changing anything that affects TUI performance or responsiveness
(navigation, refresh, rendering, startup), and before diagnosing TUI freezes or stalls.

### 2.8 `sase/memory/xprompts.md`

Read before xprompts, prompt directives, or launching agents with git/gh VCS workflow
blocks.
