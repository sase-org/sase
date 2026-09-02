# Structured Agentic Software Engineering (SASE) - Agent Instructions

## 1. Core Memory

The following memories contain core (always loaded) context:

### 1.1 SASE = Structured Agentic Software Engineering (sase)

#### 1.1.1 SASE Memory

SASE memory is this project's durable agent context: Markdown notes under `sase/memory/`
that render into this file. A note's kind — flat note or memory web — and a flat note's
`type:` frontmatter decide how it reaches you.

- **Core memory** (`type: core`) is inlined here and into every provider instruction
  shim, so it is always in your context and is paid for on every turn.
- **Reference memory** (`type: reference`) is not inlined. Only its one-line description
  is listed here; read the body on demand with your `/sase_memory_read` skill, never by
  opening the file directly.
- **Memory webs** are keyed collections: a flat descriptor note (`sase/memory/<web>.md`)
  plus a sibling directory of strand files (`sase/memory/<web>/<slug>.md`). A web's
  descriptor is always inlined here; a strand body never is — read strands on demand
  with your `/sase_memory_read` skill (`sase memory read <web>:<keyword>`, for example
  `glossary:stitch`).

Memory files are not ordinary files: before you create, edit, or delete any of them — or
propose a plan that would — use your `/sase_memory_write` skill.

#### 1.1.2 Ephemeral `sase_<N>` Workspace Directories

SASE runs agents (like you) from ephemeral workspace directories, which are full clones
of the sase repo. These directories are named `sase_<N>` where `<N>` is some integer.
You need to be mindful not to run commands outside of these workspace directories.

IMPORTANT: Do NOT mention your workspace directory (or any sibling workspace directory)
in any plan files that you generate using your `/sase_plan` skill. The agent(s) that
implement the plan might not run in the same workspace directory as you!

#### 1.1.3 Repositories

Configured linked and sidecar repositories associated with this project:

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
`/sase_repo` (unlinked GitHub repos open as external repos) and read the local checkout
instead. Web tools remain appropriate only for content a checkout does not contain, such
as blog posts, docs sites, and GitHub issue/PR discussions.

**IMPORTANT**: The `sase artifact read <ref> "<reason>"` command MUST be used to read
artifacts (so the reads are audited) from sidecar repos. Do NOT read sidecar artifact
files directly or locate, clone, or web-fetch another repo's contents any other way than
by using `/sase_repo` or `sase artifact read`!

#### 1.1.4 SASE Final Declaration

Before any normal response that ends this SASE provider turn, use your `/sase_final`
skill as the last action. This includes a final answer, an incomplete-status response,
an "I will wait" response, or any reply that intends to resume in a later turn. Only a
successfully executed plan, monitor, pipe, or questions handoff is exempt, because those
commands terminate the runner mechanically. Intending to resume later is not an
exemption.

### 1.2 Code Conventions and Gotchas (gotchas)

**Default Keymap Config**  
When changing keymaps, leader mode keys, or any configuration values, don't forget to
update the keymap configuration in the `src/sase/default_config.yml` file if necessary.

### 1.3 Rust Core Backend Boundary (rust_core_backend_boundary)

Shared backend and domain behavior belongs in the sibling Rust core repo at
`../sase-core/crates/sase_core`. Python and TUI code in this repo should call through
the Rust binding (`sase_core_rs`) or a thin local adapter instead of reimplementing core
logic here.

Use this litmus test: if a web app, CLI, editor integration, or another frontend would
need the behavior to match the TUI, treat it as core backend logic.

Presentation-only Textual state, keybindings, layout, widget rendering, and Python glue
can stay in this repo. When a change crosses the boundary, update the Rust wire/API,
bindings, and tests in `../sase-core`, then update the Python callers or adapters here.

## 2. Reference Memory

The below files contain detailed reference material. When working in their domain, you
MUST use your `/sase_memory_read` skill to review their contents. Do not read canonical
memory files directly.

1. **`sase/memory/cli_rules.md`** - Read anytime new CLI subcommands or options are
   added.
2. **`sase/memory/generated_skills.md`** - Read when working with sase agent skills (aka
   xprompt skills), which are generated from source templates in the
   `src/sase/xprompts/skills/` and deployed to managed locations (my chezmoi repo, for
   example).
3. **`sase/memory/lint_and_test.md`** - IMPORTANT: if you changed ANY file in the sase
   repo, you MUST read this note before you finish your turn. Verification is not
   optional here and the lanes are not interchangeable: this note covers the `just`
   command surface, the two-speed rule that makes `just check` the agent default and
   `just check-full` a monitor-only landing gate, the `just install` prerequisite for
   ephemeral workspace clones, and the PNG snapshot suite.
4. **`sase/memory/sase_artifacts.md`** - Read before creating, consuming, resolving,
   linking, or managing retention for SASE artifact references and indexed files.
5. **`sase/memory/sase_beads.md`** - Read before creating, updating, closing, or
   querying sase beads — bead types and tiers, the status lifecycle agents must never
   hand-edit, task-bead triage, phase-bead description prefixes, and non-cascading
   close, resolution, and note semantics.
6. **`sase/memory/sase_flags.md`** - Read before adding, deferring, or removing a SASE
   feature flag or flag bead, and before deprecating user-reaching behavior or landing
   code whose old branch must stay reachable for backward compatibility.
7. **`sase/memory/symvision.md`** - Read before fixing Symvision lint failures,
   including unused symbols, private misuse, pragmas, and epic whitelists.
8. **`sase/memory/tui_perf.md`** - Read before changing anything that affects TUI
   performance or responsiveness (navigation, refresh, rendering, startup), and before
   diagnosing TUI freezes or stalls.
9. **`sase/memory/xprompts.md`** - Read before xprompts, prompt directives, or launching
   agents with git/gh VCS workflow blocks.

## 3. Memory Webs

Each memory web below is a keyed collection. Its descriptor is always loaded, but a
strand's body is not: read strands on demand with your `/sase_memory_read` skill, for
example `sase memory read glossary:stitch -r "<why>"`.

### 3.1 Decisions (decisions)

A decision record is not a design doc or a subsystem overview — those go stale as the
code changes underneath them. A record is immutable once accepted: if the project
changes course, a new record is written and the old one is marked superseded with a
`metadata.status` plus `superseded_by` mark and a `[[...]]` back-link, never edited in
place. Read one on demand with `sase memory read decisions:<keyword> -r "<why>"`; each
record states the claim, why it was chosen over the credible alternatives, what it
costs, and the condition that would reopen it.

1. **A Gate Never Blocks An Agent** (`gates-never-block`) - Creating a gate from inside
   an agent ends that agent's turn; continuation is a gate shell's follow-up, never a
   wait.
2. **Agents Are Single-Turn** (`single-turn-agents`) - A SASE agent run is one provider
   turn; continuation is always mechanical, never a promise to resume.
3. **Completion Is Host-Owned** (`host-owned-completion`) - An agent never creates
   commits, branches, or PRs; it submits a declaration and host-owned finalizers act.
4. **Memory Links Are Authored** (`memory-links-are-authored`) - A memory file declares
   how its links are detected and rendered, and authors links inline as `[[target]]` /
   `![[target]]`.
5. **Memory Webs** (`memory-webs`) - _[partly superseded by
   `webs-render-in-their-own-section`, `memory-links-are-authored`]_ A keyed memory
   collection is a flat descriptor note plus a sibling strand directory, addressed
   web:keyword.
6. **Memory Webs Render In Their Own Section** (`webs-render-in-their-own-section`) - A
   memory web's placement in generated agent instructions follows from its kind, not
   from a `type:` declaration on its descriptor.
7. **No Retrieval Mechanism Before Its Corpus** (`corpus-before-mechanism`) - SASE does
   not build memory retrieval or linking machinery ahead of a corpus that demonstrably
   needs it.
8. **The Rust Core Is Required** (`rust-core-required`) - Shared backend behavior lives
   in sase-core with no Python fallback and no env-var backend switch.
9. **Verification Is Two-Speed** (`two-speed-verification`) - just check is the agent
   default and just check-full gates landing, because host capacity is the constraint,
   not test speed.

### 3.2 Glossary Terms (glossary)

Run `sase memory read glossary:<term> [<term> ...] -r "<why>"` before relying on any of
these SASE terms; it prints each term's definition plus every term those definitions
depend on. Pass every term you need in one command — one batched read costs far fewer
tokens than one read per term, because terms shared between definitions are printed
once. Terms are separated by semicolons; aliases follow in parentheses.

**GLOSSARY TERMS:** Agent Clan; Agent Family; Agent Hood (hood, agent neighborhood);
Agent Instruction File (agents.md file); Agent Neighbor; Agent Node; Agent Shell; Agent
Tribe; Artifact; Artifact Markdown File (artifact md file, artifact md); Artifact
Reference (ref); Chop; Core Memory (core memory); Current Project; Feature Flag; Flag
Bead (flag bead); Gate Shell; Lumberjack; Memory Strand; Memory Web; Patch; Proc
(background task); Proc Shell; Reference Memory (reference memory); Required Plugin
(required plugin); Sase Agent (agent); Sase Gate (gate); Sase Monitor (monitor); Sase
Node (node); Sase Project; Sase Repo; Sase Shell (shell); Sase Workspace (workspace);
Stitch; Strand Keyword; Task Type (task type); Xprompt; Xprompt Memory (memory file,
sase memory); Xprompt Part; Xprompt Swarm; Xprompt Workflow

### 3.3 Task Bead Types (task_types)

Every task bead can carry a `task_type` drawn from this project's catalog.
`sase bead task-type list` always shows the live catalog; read
`sase memory read task_types:<slug> -r "<why>"` for one generated type in full. This
note is the generated, always-current snapshot of the agent-creatable types below.

1. **Bug** (`bug`) - A defect an agent found while doing unrelated work, not an external
   tracker bug.
2. **CI failure** (`ci`) - A confirmed true test or lint failure you did not cause, not
   a flake.
3. **Feature** (`feature`) - An out-of-scope product or tooling idea that should not
   become a wish list.
4. **Flaky test** (`flake`) - A test that fails and then passes on an unchanged tree.
5. **Memory** (`memory`) - A sase memory note or skill that is out of date.

#### 3.3.1 File Discovered Work As Task Beads

Unless your prompt explicitly forbids creating beads (epic phase workers, for example,
must record `PROPOSED FOLLOW-UP:` notes on their own bead instead), you can and SHOULD
capture discovered follow-up work as sase task beads. Before creating any task bead, you
MUST use `/sase_new_task`.
