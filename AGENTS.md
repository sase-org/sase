# Structured Agentic Software Engineering (SASE) - Agent Instructions

> This file is generated from `sase/memory/` by `sase memory init`; edit the notes, not
> this file. SASE-launched agents get a per-invocation bundle from the same notes plus
> home memory and a provider directive. Preview it with `sase instructions render`; see
> what an agent received with `sase instructions show NAME`.

## 1. Core Memory

The following memories contain core (always loaded) context:

### 1.1 SASE = Structured Agentic Software Engineering (sase)

#### 1.1.1 SASE Memory

SASE memory is this project's durable agent context: Markdown notes under `sase/memory/`
that render into your agent instructions (this project's `AGENTS.md` and each SASE
agent's per-invocation bundle). A note's kind — flat note or memory web — and a flat
note's `type:` frontmatter decide how it reaches you.

- **Core memory** (`type: core`) is inlined into your agent instructions (this project's
  `AGENTS.md` and each SASE agent's per-invocation bundle), so it is always in your
  context and is paid for on every turn.
- **Reference memory** (`type: reference`) is not inlined. Only its one-line description
  is listed in your agent instructions; read the body on demand with your
  `/sase_memory_read` skill, never by opening the file directly.
- **Memory webs** are keyed collections: a flat descriptor note (`sase/memory/<web>.md`)
  plus a sibling directory of strand files (`sase/memory/<web>/<slug>.md`). A web's
  descriptor is always inlined into your agent instructions; its roster is too unless
  the web loads its roster on demand (read with `sase memory read roster:<web>`); a
  strand body never is — read strands on demand with your `/sase_memory_read` skill
  (`sase memory read <web>:<keyword>`, for example `glossary:stitch`).

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
  `#research*` macros.
- `sase-listen`: Standalone text-to-speech CLI for turning Markdown into chaptered,
  loudness-normalized MP3 audio editions and publishing private podcast feeds.
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

Only the root SASE agent — the provider turn SASE launched — submits the final
declaration; if you were spawned or forked as a helper (a native subagent), return your
result to your parent instead. Before any normal response that ends this SASE provider
turn, use your `/sase_final` skill as the last action. This includes a final answer and
an incomplete-status response; an unfinished turn still declares so its work is
committed. Never end a turn to wait for a command or to resume later: nothing can wake
you, so hand long commands to `/sase_monitor` before starting them. Every root turn ends
through `/sase_final`, including handoff turns: a staged handoff is adopted by the host
after finalizers settle.

### 1.2 Code Conventions and Gotchas (gotchas)

**Default Keymap Config**  
When changing keymaps, leader mode keys, or any configuration values, don't forget to
update the keymap configuration in the `src/sase/default_config.yml` file if necessary.

### 1.3 Rust Core Backend Boundary (rust_core_backend_boundary)

Shared backend and domain behavior belongs in the `sase_core` crate of the linked
`sase-core` repo; open it with `sase repo open sase-core` and work in the printed path.
Python and TUI code in this repo should call through the Rust binding (`sase_core_rs`)
or a thin local adapter instead of reimplementing core logic here. A binding that sase
calls also needs sase's `sase-core-revision.txt` CI pin moved past its sase-core commit
(see `docs/rust_backend.md`).

Use this litmus test: if a web app, CLI, editor integration, or another frontend would
need the behavior to match the TUI, treat it as core backend logic.

Presentation-only Textual state, keybindings, layout, widget rendering, and Python glue
can stay in this repo. When a change crosses the boundary, update the Rust wire/API,
bindings, and tests in the linked `sase-core` checkout, then update the Python callers
or adapters here.

## 2. Reference Memory

The below files contain detailed reference material. When working in their domain, you
MUST use your `/sase_memory_read` skill to review their contents. Do not read canonical
memory files directly.

1. **`sase/memory/ace.md`** - Read before changing anything under `src/sase/ace/`.
2. **`sase/memory/cli_rules.md`** - Read anytime new CLI subcommands or options are
   added.
3. **`sase/memory/demos.md`** - Read before editing VHS tapes under `demos/tapes/`.
4. **`sase/memory/dispatch.md`** - Read before dispatching agents to a remote machine
   with `%dispatch`.
5. **`sase/memory/docs_writing.md`** - Read before adding, moving, or editing anything
   under `docs/`, `mkdocs*.yml`, or a sase.sh link in code.
6. **`sase/memory/generated_skills.md`** - Read when working with sase agent skills (aka
   macro skills), which are generated from source templates in the
   `src/sase/macros/skills/` and deployed to managed locations (my chezmoi repo, for
   example).
7. **`sase/memory/lint_and_test.md`** - If you changed any file tracked by git in the
   sase repo (excluding file changes in the separate repos contained in the sase/repos/
   directory), you MUST read this note before you finish your turn.
8. **`sase/memory/macros.md`** - Read before macros, prompt directives, or launching
   agents with git/gh VCS workflow blocks.
9. **`sase/memory/sase_artifacts.md`** - Read before creating, consuming, resolving,
   linking, or managing retention for SASE artifact references and indexed files.
10. **`sase/memory/sase_beads.md`** - Read before creating, updating, closing, or
    querying sase beads — bead types and tiers, the status lifecycle agents must never
    hand-edit, task-bead triage, phase-bead description prefixes, and non-cascading
    close, resolution, and note semantics.
11. **`sase/memory/sase_flags.md`** - Read before adding, deferring, or removing a SASE
    feature flag or flag bead, and before deprecating user-reaching behavior or landing
    code whose old branch must stay reachable for backward compatibility.
12. **`sase/memory/symvision.md`** - Read before fixing Symvision lint failures,
    including unused symbols, private misuse, pragmas, and epic whitelists.
13. **`sase/memory/tools.md`** - Read before changing, adding, or vendoring anything
    under `tools/`.
14. **`sase/memory/tui.md`** - Read before changing the SASE TUI, its live screenshot
    tooling, visual snapshots, or performance-sensitive UI paths.

## 3. Memory Webs

Each memory web below is a keyed collection. Its descriptor is always loaded with its
roster unless the descriptor says the roster loads on demand; read those with
`sase memory read roster:<web>`. A strand's body is not: read strands on demand with
your `/sase_memory_read` skill, for example
`sase memory read glossary:stitch -r "<why>"`.

### 3.1 Decisions (decisions)

A decision record is not a design doc or a subsystem overview — those go stale as the
code changes underneath them. A record is immutable once accepted: if the project
changes course, a new record is written and the old one is marked superseded with a
`metadata.status` plus `superseded_by` mark and a `[[...]]` back-link, never edited in
place. Each record states the claim, why it was chosen over the credible alternatives,
what it costs, and the condition that would reopen it.

**Roster on demand.** This web's 32 decisions are not listed here. You MUST read the
DECISIONS roster with `sase memory read roster:decisions -r "<why>"`:

- before writing or revising a SASE plan; cite each governing decision as
  `decisions:<keyword>`
- when performing research, to find decisions related to the question before
  recommending anything
- before changing behavior a decision may govern when no plan already cites it

Read one decision with `sase memory read decisions:<keyword> -r "<why>"`.

### 3.2 Glossary Terms (glossary)

Run `sase memory read glossary:<term> [<term> ...] -r "<why>"` before relying on any of
these SASE terms; it prints each term's definition plus every term those definitions
depend on. Pass every term you need in one command — one batched read costs far fewer
tokens than one read per term, because terms shared between definitions are printed
once. Terms are separated by semicolons; aliases follow in parentheses.

**GLOSSARY TERMS:** Agent Clan; Agent Data Card (card); Agent Data Card Block (card
block); Agent Data Deck (deck); Agent Hijack (hijack, hijacked agent); Agent Hood (hood,
agent neighborhood); Agent Instruction File (agents.md file); Agent Neighbor; Agent
Node; Agent Relation Jump Target (agent jump target); Agent Tab (agents sub-tab, agents
sub-tabs); Agent Tribe; Agent Turn; Artifact; Artifact Markdown File (artifact md file,
artifact md); Artifact Reference (ref); Clan Wave; Core Memory (core memory); Current
Project; Deck Panel (deck layout); Failure Signature; Feature Flag; Flag Bead (flag
bead); Gate Turn; Goal (⌖); Instruction Bundle (instruction bundle); Instruction
Manifest (instruction manifest); Job (Chop); LLM Calls; Machine Tab; Macro (xprompt);
Macro Invocation (smack, macro reference, macro ref); Macro Memory (memory file, sase
memory); Macro Part; Macro Swarm; Macro Workflow; Memory Strand; Memory Web; Named Proc;
Nav Item (navigation item); Nav Section (navigation section); Node Panel; Oneshot
Service Proc (oneshot, background command); Patch; Proc; Project Tag (macro project
tag); Prompt Composer (composer, prompt bar, prompt input widget); Prompt Stash (stash);
Raw Prompt; Receipt; Reference Memory (reference memory); Required Plugin (required
plugin); Routine (Lumberjack); Sase Agent (agent); Sase Agent Session (agent session);
Sase Gate (gate); Sase Monitor (monitor, monitor turn); Sase Node (node); Sase Project;
Sase Repo; Sase Scheduler (scheduler, AXE); Sase Service (service host); Sase Turn
(turn); Sase Workspace (workspace); Service Proc; Stash Trash; Stitch; Strand Keyword;
Task Type (task type); Tool Catalog; Tool Run; Triage Verdict; Usage Window
(usage-window)

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
