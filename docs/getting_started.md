---
title: "Getting Started: Your First 15 Minutes"
description: >-
  A hands-on tour: install SASE, check provider readiness, launch a safe first agent
  run, find and reuse its artifacts, and pick up the vocabulary you'll keep bumping into
  in about 15 minutes.
---

# Getting Started: Your First 15 Minutes

SASE (pronounced "sassy" — yes, really) is a coordination layer that sits above
coding-agent CLIs like Claude Code, Codex, Antigravity CLI (`agy`), Qwen Code, OpenCode,
Meta's Muse Code, or xAI's Grok Build. This guide is the practical on-ramp: by the end
you'll have installed `sase`, checked that a provider CLI is ready, launched a safe
read-only agent run, found the resulting agent record, handed one durable artifact to
another run, and picked up the vocabulary you'll keep bumping into in the rest of the
docs. Plan on roughly fifteen minutes at a terminal, plus however long your favorite
model takes to think.

## Step 1 — Install SASE

SASE needs Python 3.12+, [`uv`](https://docs.astral.sh/uv/), and one authenticated
coding-agent CLI such as Claude Code, Codex, Antigravity CLI (`agy`), Qwen Code,
OpenCode, Meta's Muse Code, or xAI's Grok Build. With Python and `uv` in place:

```bash
uv tool install sase
sase version
```

If `sase version` prints the SASE package plus the `sase-core-rs` package, the CLI is
installed. The first install can stretch past 90 seconds when `uv` has to fetch wheels;
that's normal, not a hang.

**What you just did.** Installed the public `sase` CLI and its Rust core extension as a
user tool, without cloning the repository or setting up a contributor environment.

Also worth doing now: `sase completion install` writes a `<TAB>`-completion script for
your shell (zsh, bash, or fish) and verifies it actually loads. See
[Shell Completion](completion.md) for details.

## Step 2 — Check Provider Readiness

SASE orchestrates a supported provider CLI and still relies on the provider's own
authentication flow. Inventory the supported CLIs, then run the read-only doctor before
the first agent launch:

```bash
sase agent-cli
sase doctor
```

If the provider check reports a missing executable or an authentication gap, install and
authenticate one provider CLI, then run `sase doctor` again. Among SASE's built-in
providers, Muse Code is the one SASE can currently install itself: use
`sase agent-cli install muse --dry-run` to inspect the downloaded script's URL, digest,
command, and target, then `sase agent-cli install muse` to confirm and run it. Other
built-in providers use the install commands in the provider guide.
[Installing & Authenticating Agent Providers](agent_providers.md) has the per-provider
install and auth commands plus the complete provider/model selection options; the
[LLM provider reference](llms.md) covers how SASE integrates each provider once it is
ready.

**What you just did.** Verified that SASE can find a usable coding-agent provider before
spending time on an agent run.

## Step 3 — Launch A Safe First Agent

Start with a read-only task in SASE's managed `home` project. Use one launch form: the
normal form when SASE can auto-detect an installed provider CLI, or the explicit form
when Muse Code or Grok Build is your provider. SASE never auto-detects `muse` or `grok`
from PATH because both are generic executable names; select them explicitly with a
provider/model directive. Grok Build can still be reached automatically through the
shipped `@xsmall`, `@small`, and `@medium` pools, or as the last `@xlarge` fallback
candidate, when its CLI is installed:

```bash
# Auto-detected providers:
sase run "#git:home summarize this workspace's layout; do not change files"
# Muse Code:
sase run "%model:muse/muse-spark-1.2 #git:home summarize this workspace's layout; do not change files"
# Grok Build:
sase run "%model:grok/grok-4.6 #git:home summarize this workspace's layout; do not change files"
# Then, while it is still running:
sase agent list
```

The `#git:home` prefix targets SASE's built-in `home` sandbox. On first use, SASE
bootstraps that managed project with a bare git repository, a primary checkout, and
generated SDD scaffolding, then launches the provider CLI in an isolated numbered
workspace managed by SASE. Prompts with no workspace reference are normalized to
`#git:home` automatically, so the bare form
`sase run "summarize this workspace's layout; do not change files"` is equivalent. That
isolation is what lets you fire off several agents at once without them colliding, and
what lets a failed run be retried without touching your primary checkout.

The launched agent gets its own durable record on disk: prompt, reply transcript,
artifacts directory, status, and workspace path. Default `sase agent list` shows
**running** agents only. After the run finishes, use `sase agent list -a` (recent
DONE/FAILED, capped at 50 most-recent per project) or open ACE's Agents tab to find the
completed record.

**What you just did.** Dispatched a read-only coding-agent run inside an explicit
[workspace](workspace.md), then looked up the resulting SASE agent record.

## Step 4 — Open ACE And Find The Result

ACE is the TUI control surface. Open it:

```bash
sase ace
```

ACE has three top-level tabs:

- **Agents** — live and recent agent records. Find the run you just launched: prompt,
  reply transcript, workspace path, status, retry chain.
- **Artifacts** — views for stitches, Patches, beads, configured document providers such
  as Plans and Research, and captured files. The Patches view contains every Patch on
  the project. A **Patch** is SASE's durable record of one PR-sized unit of work; think
  of it as the long-lived sibling of a pull request that holds the description, parent,
  status (WIP → Draft → Ready → Mailed → Submitted), commits, hooks, comments, and
  mentor activity all in one place. The [Patch guide](change_spec.md) goes deeper when
  you're curious. This first read-only run should not have created one yet; editable
  committed work is where Patches appear.
- **Axe** — the background daemon's view: scheduled jobs, hooks waiting to complete,
  mentor launches, error digests. ACE auto-starts AXE the first time it opens, so this
  tab is already ticking before you click it.

The top bar's colored `+<project>` chip is the [current project](ace.md#current-project)
— the project you most recently launched an agent on (or promoted with
`sase project set-current`). After the `#git:home` run above, that chip is `+home`.
First-open Artifacts filters seed from it; they do not lock you into that project. Press
`?` for help and `q` to quit.

**What you just did.** Observed one `sase run` produce a persistent agent artifact
visible in [ACE](ace.md), with [AXE](axe.md) handling lifecycle work in the background.

## Step 5 — Try One Tiny Edit

After you have seen the agent record, try a low-risk change:

```bash
sase run \
  "#git:home create or update notes.md with one short note about SASE workspaces. Then run: sase artifact create -p notes.md -l 'Workspace note'"
sase agent list -a
```

Now the agent has permission to make a visible diff in its isolated numbered workspace.
Your own repositories and the `home` primary checkout stay untouched unless you
explicitly bring changes back. When the agent commits its work, SASE's commit workflow
records a Patch that you can review in ACE's Artifacts tab, under Patches, before
landing or submitting anything.

Wait until that run finishes before continuing. Default `sase agent list` shows
**running** agents only, so the row disappears from the default list when the run ends.
Watch it on ACE's Agents tab, or poll `sase agent list -a` until that row's status is
`DONE` or `FAILED`. `-a` still includes running agents; you are waiting for the status
to change, not for the row to appear. The second instruction registers a durable
snapshot while leaving the tracked `notes.md` in the workspace.

For your own repositories, use `#git:<name>` to target a managed project or
`#git:<bare-repo-path>` to register an existing bare repository. Provider plugins add
other workspace references, such as `#gh:<owner>/<repo>` for GitHub. The
[workspace guide](workspace.md) has the full model.

**What you just did.** Moved from a read-only run to a small editable task after
confirming where SASE records agent state.

## Step 6 — Hand Off Existing Work With Artifact References

An agent handoff is more reliable when it names the exact prior artifact instead of
describing it loosely. List the explicit files SASE indexed for `home`:

```bash
sase artifact list --project home --explicit --limit 10
```

The `Workspace note` row's `REF` column contains a durable file reference such as
`file:explicit:0123456789abcdef01234567`. Copy the exact value from your output and
inspect it without launching an agent:

```bash
sase artifact show file:explicit:0123456789abcdef01234567
```

Then add `@` when the same reference appears inside a prompt:

```bash
sase run "#git:home read @file:explicit:0123456789abcdef01234567 and summarize it"
```

Replace the sample reference with one from your own `REF` column. This leading-`@`
distinction is intentional: `sase artifact show`, `path`, and `open` accept the bare
logical reference, while launch prompts use `@kind:payload` so SASE can find and expand
references embedded in ordinary prose. `sase artifact list` inventories the persistent
artifact-file index, not every kind of artifact reference. Rows with `file:explicit:`
were registered with `sase artifact create`; `file:default:` rows are media that SASE
persisted automatically while finalizing successful runs.

Artifact references cover more than indexed files:

| Prompt form               | What it identifies                                                   |
| ------------------------- | -------------------------------------------------------------------- |
| `@file:<source>:<digest>` | Indexed file; source is `explicit` or `default`                      |
| `@file:<absolute-path>`   | One file below a configured allow-listed root                        |
| `@<document-kind>:<path>` | One document in a configured sidecar, such as `plan:` or `research:` |
| `@bead:<id>`              | One published bead page in the current project                       |
| `@agent:<global-name>`    | One published agent page in the current project                      |
| `@patch:<name>`           | One Patch                                                            |
| `@stitch:<repo>@<sha>`    | One repository revision                                              |

Use `@plan:<path>` for the built-in plans sidecar. `@commit:` remains an alias for
`@stitch:`; the old `#ref/<kind>` renderer syntax has been retired.

ACE can supply these without memorizing the grammar. Type `@` in the prompt bar for the
grouped reference menu, or press `%` on an Artifacts entry to open **Copy as…**. The
editor LSP completes canonical `@stitch:` payloads from local git checkouts, excluding
SDD sidecar repositories. ACE's prompt bar currently lists both canonical and
compatibility kinds, but its repository-history picker is still attached to `@commit:`;
that alias and `@stitch:` resolve identically at launch. ACE also lists `@patch:`
without enumerating Patch names, so use `%` on the Patch or type its name. Choose
**Reference in new agent prompt** to open a prompt pre-filled with the entry's project
and prompt-ready `@` reference; choose **Copy artifact reference** when you only want
the reference on the clipboard.

At launch, document, file, bead, and agent references become local `@absolute-path`
tokens. A stitch becomes `stitch <full-sha> in <repo> (checkout: <path>)`; a Patch
becomes `the <name> Patch in project <project>` plus an inspection hint. That hint
currently names `sase patch show`, which is not a `sase` command — do not run it.
Inspect a Patch from ACE's Patches view, with `sase patch search`, or with
`sase patch current` when you are already in that Patch's workspace. A historical
`@bug:` reference becomes its issue number and provider URL. A malformed or missing
known reference stops the launch with a diagnostic instead of silently giving the agent
bad context. Inline-code and fenced-code examples stay literal.

See the [`sase artifact` command reference](configuration.md#sase-artifact) for
inspection, path, viewer, and repair commands. The
[Artifact References](artifact_references.md) page documents canonical forms, project
context, compatibility aliases, and allow-listed files. The
[prompt preprocessing reference](llms.md#prompt-preprocessing-pipeline) explains
expansion order and literal regions.

**What you just did.** Passed one durable output from a completed run to a new agent
without depending on chat history or a recycled workspace path.

## Step 7 — Reuse The Prompt As An XPrompt

A one-off prompt is fine once. The second time you find yourself reaching for it, wrap
it as an **XPrompt** so you're not retyping the same paragraph forever. Create
`sase/xprompts/til.md` at the project root where you run `sase`:

```markdown
Append one Today-I-Learned entry to `til.md` about something useful in this workspace.
Keep it to two sentences. If the file does not exist, create it.
```

Now the same agent run is one tag:

```bash
sase run "#til"
```

That is the smallest XPrompt shape: a single Markdown file becomes a reusable prompt
part. Because this prompt has no workspace reference, the same `#git:home` default kicks
in at launch. XPrompts also support YAML files with typed inputs, multi-step workflows
(prompt parts, Python, bash, parallel fan-out, approvals), and `---` separators for
multi-agent dispatch. The [XPrompts guide](xprompt.md) covers the full surface, and the
[workflow spec reference](workflow_spec.md) documents the YAML form.

**What you just did.** Turned a one-off prompt into a reusable XPrompt, the smallest
unit of repeatable agent work in SASE.

## Step 8 — Plan Bigger Work With SDD And Beads

When a task is too big to hand to a single agent and hope, SASE asks you to write a plan
first. **Spec-Driven Development (SDD)** keeps those plans as first-class artifacts on
disk under three (admittedly whimsical) names: ordinary plans are _tales_, and
executable multi-phase plans are _epics_. Any of them can be filed as a **bead**: a
git-portable, issue-like work unit with status, dependencies, and an assignee.

The smallest useful loop:

```bash
sase bead onboard         # walks through the issue-tracking quick start
sase bead ready           # lists ready task beads whose blockers are closed
sase bead show <bead-id>  # inspects one bead in detail
```

For a self-contained follow-up that does not need an epic, agents first run
`/sase_new_task`; when it is genuinely new, create a standalone task bead with
`sase bead create --type 'task(bug)' --title "Follow up" --size small -f location=src/foo.py -f repro='fails on retry'`,
move it to `ready` when it is ready for triage, and launch it with
`sase bead work <task-id>`. AXE also turns stored `ready` tasks into notification gates
where a reviewer can launch or close them.

Approving a structured epic plan files its epic and phase beads, wires their
dependencies, and automatically invokes the same path as
`sase bead work <epic-id> --yes`. Before it spawns anything, that path sets the epic's
internal launch-readiness marker, assigns every remaining phase bead to its
deterministic worker, assigns the epic to the land worker, and commits the complete
launch checkpoint. Unless the launch uses `--no-push`, the existing-epic path also runs
managed store synchronization before dispatch; a remote-backed detached bead store must
actually publish the checkpoint. It then launches one agent per remaining phase plus the
final land agent. Dependency waits require both the blocking agent to finish
successfully and its bead to close; the land agent waits for every phase bead. You can
still run `sase bead work <epic-id>` manually to retry remaining work.

**What you just did.** Stepped from one-shot prompts into
[Spec-Driven Development](sdd.md) with [Beads](beads.md) as dependency-aware work units.

## The Component Map

The names you'll keep bumping into, in one place:

- **[ACE](ace.md)** — the TUI control surface for Patches, agents, notifications, and
  automation.
- **[Current project](ace.md#current-project)** — the project SASE treats as working
  context: in practice, the one you most recently launched an agent on (or promoted with
  `sase project set-current` / ACE Projects tab `c`). `sase project current` prints it.
  The working directory never sets it, and there may be none.
- **[AXE](axe.md)** — the background automation daemon. Runs hooks, mentor launches,
  comment polling, dependency unblocking, error digests.
- **`sase run`** — the entry point that launches an agent or workflow. See the
  [CLI reference](cli.md).
- **[Workspaces](workspace.md)** — isolated numbered clones managed by SASE so agents
  can work in parallel without touching your primary checkout.
- **[Patches](change_spec.md)** — durable PR-sized review records: status lifecycle,
  commits, hooks, comments, mentors.
- **Artifact references** — durable `@kind:payload` locators that put files, documents,
  chats, beads, agents, commits, and bugs into a launch prompt. Resolve them with
  `sase artifact show`, `path`, or `open`; complete, copy, or hand them off from
  [ACE](ace.md).
- **[Beads](beads.md)** — dependency-aware, git-portable plan, phase, and standalone
  task work units.
- **[Glossary](memory.md#glossary)** — per-project definitions of the terms your team
  keeps reusing, authored in `sase/sase.yml`. Agents fetch one on demand with
  `sase glossary read <term> -r "<why>"` instead of carrying every definition in memory
  (`-r` is required — a read is never printed unless it is recorded). In ACE, both
  shortcuts are prompt-bar keys: from a prompt pane in NORMAL mode, `K` previews the
  term under the cursor and `gG` opens the browse-and-edit
  [Glossary panel](ace.md#glossary-panel). `gT` opens the
  [Snippets panel](ace.md#snippets-panel).
- **[XPrompts](xprompt.md)** — reusable prompt templates and YAML workflows with typed
  inputs and multi-agent fan-out. See also [workflow specs](workflow_spec.md).
- **[SDD](sdd.md)** — Spec-Driven Development. Plans and epics as first-class artifacts
  on disk.
- **Procs** — durable records for background operations such as a sync, an accept, or a
  detached task launch. Every proc runs under its own supervisor and outlives the client
  that submitted it; a session is attribution only, and historical `tui` and `detached`
  rows stay readable. Inspect them with `sase proc list` / `sase proc show`, or on the
  Admin Center's [Procs tab](ace.md#procs-tab).
- **[Monitors](monitors.md)** — agent-family members used to hand off a slow command
  (`just check-full`, a CI wait, a deploy) at the end of an agent turn. A detached
  supervisor runs the command, and an optional follow-up agent shell returns under the
  same agent family; the family keeps its one runner slot for the monitor and then the
  follow-up. SASE reports explicitly if that follow-up cannot inherit the monitor's
  workspace.
- **[Plugins and providers](plugins.md)** — model and VCS providers behind a common
  boundary: Claude Code, Antigravity CLI (`agy`), Codex, Qwen Code, OpenCode, Muse Code,
  Grok Build for agents; bare git and GitHub for version control.

## What To Read Next

- [SASE: Structured Agentic Software Engineering](blog/posts/structured-agentic-software-engineering.md)
  — the launch post and conceptual front door.
- [CLI reference](cli.md) — a discovery index of `sase` commands (compact `sase --help`
  lists only the common ones; `sase --full-help` prints every command).
- [The SASE repository](https://github.com/sase-org/sase) — source, issues, and project
  direction.
