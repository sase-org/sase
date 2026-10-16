---
title: Glossary
description: Every SASE term, generated from the glossary memory web.
---

<!-- generated, do not edit; source: sase/memory/glossary/*.md (tools/render_glossary; run just fix to regenerate) -->

# Glossary

SASE's shared vocabulary, generated from the
[glossary memory web](https://github.com/sase-org/sase/tree/master/sase/memory/glossary).
Terms are sorted A–Z and each anchor matches its memory slug.

## Agent Clan {#agent-clan}

An agent clan is a named, rootless container for related agents whose members may run in
parallel or in clan waves derived from their `%wait` edges ([Clan Wave](#clan-wave)).
Every member is named inside the clan's hood (`<clan>.<suffix>`) and declares
`%clan:<clan>`; the clan name is reserved and is never itself an agent.

An agent clan node's status aggregates its member agent nodes, except that a clan with
exactly one running member (`STARTING` included) shows exactly that node's status — its
label, styling, and row overlays such as `FINALIZING` — rather than a generic `RUNNING`.
Only a member that needs the user (asking, awaiting plan review, or failed) outranks it.

## Agent Data Card {#agent-data-card}

_Also known as: card, agent data cards._

An agent data card is one titled unit of detail inside an agent data deck, such as
Context, Reply, one file's diff, or LLM Calls. A deck panel shows a multi-card deck
spread — every card on one scrollable page, separated by titled rules — when the cards
fit within `ace.agent_decks.spread_max_screens` panel heights, and paged — one card at a
time — otherwise. `Ctrl+J`/`Ctrl+K` move to the next or previous card in both modes, and
a paged deck keeps the chosen card (for example Reply) as the selection moves between
nodes. A card can contain optional [Agent Data Card Block](#agent-data-card-block)
units, which never nest.

## Agent Data Card Block {#agent-data-card-block}

_Also known as: card block, card blocks._

An agent data card block is one titled, stably identified unit inside an
[Agent Data Card](#agent-data-card) (deck -> card -> block); blocks are optional and
never nest. A session Reply card holds one block per concrete [Sase Turn](#sase-turn),
landing on the newest block, with `(` / `)` stepping between blocks and a one-row block
rail timeline.

## Agent Data Deck {#agent-data-deck}

_Also known as: deck, agent data decks._

An agent data deck is a named, ordered set of agent data cards about the selected sase
node, shown in an Agents-tab deck panel. The built-in decks are Main (a Context card and
a Reply card — titled Output for named procs, monitors, gates, and workflow steps — or
one Summary card for agent clans and tribe panels), Files (one card per diff or attached
file), Tools (the LLM Calls card), and FINAL (an Overview card plus one card per
finalizer instance, showing how the node's host-owned finalizers ran). A deck is
presentation only and owns no agent data; `Ctrl+N`/`Ctrl+P` cycle the focused deck panel
through the decks, and the `p` picker jumps to one (`m`, `f`, `t`, `n`).

## Agent Hood {#agent-hood}

_Also known as: hood, agent neighborhood._

An agent hood is a group of agents that are all named with the same `<name>.` prefix.
For example, agents named `foo.bar`, `foo.baz`, and `foo.bar.1` are all apart of the
same `foo` agent hood. The agent `foo`, if it exists, is also considered part of the
`foo` agent hood.

## Agent Instruction File {#agent-instruction-file}

_Also known as: agents.md file._

An agent instruction file is a `.md` file that an agent CLI reads automatically when
working in a directory that contains it. `AGENTS.md` is the canonical name, kept beside
a byte-identical `CLAUDE.md` copy for older Claude Code versions; Antigravity (agy),
Qwen Code, and OpenCode all read `AGENTS.md` through native discovery.
`sase memory init` renders the project files from the notes in `sase/memory/`. A
SASE-launched agent does not read these files: it gets a per-invocation
[Instruction Bundle](#instruction-bundle) built from the same notes instead.

## Agent Neighbor {#agent-neighbor}

An agent neighbor is any agent that is in the same agent hood as another agent. For
example, agents named `foo`, `foo.baz`, and `foo.bar.1` are all neighbors of each other
because they are all in the same `foo` agent hood.

## Agent Node {#agent-node}

An agent node is the Agents-tab node for a non-dismissed sase agent: an agent session
node, or an agent turn node when the agent has no session. A session node's member rows
are sase turn nodes, not agent nodes. Dismissal removes the node, not the sase agent's
identity.

## Agent Relation Jump Target {#agent-relation-jump-target}

_Also known as: agent jump target._

An agent relation jump target is what an Agents-tab numeric keymap jumps to: a sase
node, or a dismissed sase agent that opens read-only in the Archive, reached through one
of the selection's agent relations. Each one is a numbered row, its number chip at the
left, in that relation's roster section: `SESSION TURNS` (an agent session's sase turns,
monitor and gate turns included), `NEIGHBORS` (the selected agent's agent neighbors,
dismissed ones included), `CLAN MEMBERS` (an agent clan's direct members), or
`TRIBE MEMBERS` (an agent tribe's top-level clans, sessions, workflows, and agents). The
rosters shown for one selection share a single number sequence: `0`–`9`, or `00`–`99`
past ten targets, capped at 100. Typing a number selects its target and reveals it
through any folds; if the target is a dismissed sase agent, it opens read-only in the
Archive. The jump panel, the sticky footer below the deck panels, lists every live agent
relation jump target.

Only numbered rows are agent relation jump targets. Rows behind a `… +N more` tail,
unnumbered child rows, `… also listed under SESSION TURNS` duplicates, and tribe
`CLAN SUMMARIES` / `PROMPTS` chips that reuse a member's number are not. Plain "jump
target" is ambiguous, and none of its other uses is an agent relation jump target: `'`
entry hints (including the `AgentJumpTarget` type in `jump_hints.py`), `,j`/`,J` unread
and stopped-agent jumps, `Ctrl+]` prompt-definition jumps, and Admin Center section and
`,L` error-log jumps. The Artifacts tab's relation panel `<`/`>` keys follow artifact
relations, not agent relations.

## Agent Tab {#agent-tab}

_Also known as: agents sub-tab, agents sub-tabs, agent tabs._

An agent tab is an exclusive, root-level, presentation-only placement of top-level sase
agents on the Agents tab. The field is always named `agent_tab`, never a bare `tab`. A
named tab is authored with `%tab:<name>`; agents without one land on the default tab,
labeled `main`, or on a derived [Machine Tab](#machine-tab) when machine tabs are on.
Membership follows the presentation root (session, clan generation, or workflow), so a
container never splits across tabs. The strip shows once two or more tabs exist; `]` /
`[` cycle tabs, and selection, folds, and sticky panels are kept per tab. A tab never
changes where an agent runs, its identity, clan, session, or
[Agent Tribe](#agent-tribe).

## Agent Tribe {#agent-tribe}

An agent tribe is a user-facing label for related agents across clans and sessions.
Assign a tribe at launch with `%id(tribe=<tribe>)` or `#tribe:<tribe>` for an auto-named
agent, `%id(<id>, tribe=<tribe>)` for an explicitly named agent, or
`%clan(<clan>, tribe=<tribe>)` for a clan. Tribes can also be managed after launch with
`sase agent tribe` and are displayed with an `@` prefix.

## Agent Turn {#agent-turn}

An agent turn is one concrete LLM/provider run. It holds a workspace claim while active
and is the execution row shown by `sase agent list`. Formerly called an agent shell.

## Artifact {#artifact}

A SASE artifact is any durable record addressable by an artifact reference: a sidecar
document such as a plan or a research report, a bead, a completed agent, a Patch, a
stitch, a goal, or an indexed file. Every artifact has a canonical `<kind>:<argument>`
identity and an artifact markdown file that carries its typed links.

## Artifact Markdown File {#artifact-markdown-file}

_Also known as: artifact md file, artifact md._

An artifact markdown file is the Markdown document that carries one artifact's typed
links. A Markdown artifact is its own artifact md file. A non-Markdown file uses a
sibling `<stem>.md`; beads, agents, and Patches use their generated page, which is a
projection of the artifact's own store. A commit has none — links to a stitch render on
the other artifact. The file is created the first time the artifact acquires a link.
SASE renders those links as a table of hyperlinks near the top of the file. Agents write
links with `sase artifact link` and read artifacts with `sase artifact read`; they never
hand-edit a generated page.

## Artifact Reference {#artifact-reference}

_Also known as: ref._

An artifact reference (ref) is a typed `@<kind>:<argument>` citation in an agent prompt.
Builtin kinds are `@stitch`, `@patch`, `@bead`, `@agent`, `@goal` (which cites a goal
and never binds one), and the special `@file`; artifact repos add document kinds such as
`@plan` and `@research` through a project's `ref:` config, written inline or with
`use: <plugin>@<provider>` from an installed provider plugin listed as a Required
Plugin. Every ref expands to prompt text, is recorded against the agent that used it,
and publishes as a `[@kind:arg][N]` link.

## Clan Wave {#clan-wave}

A clan wave is a dependency layer of direct members in one generation of an agent clan.
A member is in wave 1 when none of its declared waits resolves to another member in the
same generation. Otherwise it follows one plus the highest wave of the members it waits
on. A wave is a layer, not a barrier, so later waves may start while earlier work is
still running. An epic land member may form an unnumbered `∎` seal stage when it alone
makes up the final layer and another layer exists. The Agents tab shows waves only for
layered clans: clans with two or more layers, or with any member caught in a wait cycle.

## Core Memory {#core-memory}

_Also known as: core memory._

A SASE memory that renders as always-loaded context. Author new notes with type: core
frontmatter; they are inlined into AGENTS.md and every provider instruction shim. Legacy
type: short still parses as core.

## Current Project {#current-project}

The current project is the one sase project SASE treats as your working context: in
practice, the one you most recently launched an agent on. It is derived, not stored —
the first entry in the shared VCS macro MRU store (`~/.sase/vcs_macro_mru.json`) that
maps to an enabled project, where a Patch entry yields its owning project.
`sase project set-current` and the Projects tab in sase's TUI promote a project without
launching; the working directory never does, and there may be none. It supplies only
display and defaults, namely the TUI top-bar `+<project>` chip and the first-open value
of project filters, so it never overrides an explicit choice, project lifecycle state,
or what a command targets. `sase project current` prints it.

## Deck Panel {#deck-panel}

_Also known as: deck layout._

A deck panel is one Agents-tab detail region that shows one agent data deck. The Agents
tab shows one to three deck panels: one panel, two in a stacked split (`\`, one above
the other) or a side-by-side split (`|`, side by side), or four three-pane T shapes with
a full-span main panel, following vim's split naming. One split-key rule governs them
all: `\` draws a stacked divider and `|` a side-by-side divider; if that kind of divider
already spans the whole area, the key erases it and the side you are on grows to fill
the space; otherwise, with fewer than three panels, the key draws the divider through
the focused panel; with three panels, the key turns the layout. `Ctrl+F` / `Ctrl+B` move
the logical focus that deck, card, scroll, search, and fold keys act on, `Ctrl+Shift+F`
/ `Ctrl+Shift+B` (aliases `>` / `<`) swap the focused panel's session with the next /
previous panel, `Ctrl+Shift+D` (alias `Ctrl+X`) closes the focused panel, `Ctrl+T` turns
the layout, and `Z` zooms the focused deck panel in place. The identity header and the
jump panel span every deck panel and belong to none.

## Failure Signature {#failure-signature}

A failure signature is the normalized, extractor-versioned identity of one durable
failure item from a [Tool Run](#tool-run). It keeps a bounded display, locator paths,
and occurrence count so observations of the same failure can be classified and grouped
without requiring retained raw logs.

## Feature Flag {#feature-flag}

A feature flag is a code-owned boolean route for SASE behavior that reaches users before
it is ready to become unconditional. Flags are temporary, are created through
`sase flag new`, and must be removed through their dedicated `flag` task bead.

## Flag Bead {#flag-bead}

_Also known as: flag bead._

A flag bead is a task bead of type `flag`: the dedicated top-level removal dossier for
one SASE feature flag. It owns the flag key, kind, both-branch prose, and the
`remove_by_date` and `remove_by_release` thresholds that drive `FlagTriage`. It is not a
fourth issue type and not the epic or task that introduced the behavior.

## Gate Turn {#gate-turn}

A gate turn is a session-attached turn — like a monitor turn or an agent turn — that
owns one durable command-backed decision. It publishes the decision, outlives the agent
that created it, runs the option commands the reviewer selects, and hands their outcome
to the next session member. A gate carrying a `turn` block (`turn_kind: "gate"`) is a
gate turn. Creating a gate turn from inside an agent hands off and kills that agent's
turn; if the creator had no agent session yet, attaching the gate turn promotes it into
one. Members are named `<session>--gate`, then `--gate-0`, `--gate-1` — the same suffix
scheme a sase monitor uses for `--mon`. A gate turn settles as `completed`, `failed`,
`timeout`, `stopped`, or `lost`, and launches only the follow-up recorded for the branch
the reviewer selected. A gate turn contains no LLM and never keeps its creator alive
while awaiting a human. Inspect gate turns with `sase gate`. Formerly called a gate
shell.

## Goal {#goal}

_Also known as: goals, ⌖._

A goal is a person-owned durable outcome record with identity `goal:<id>` (shown as
`⌖<id>`). It moves through `active`, `review`, `done`, and `dropped`; Running versus
Idle is derived from agent liveness and never stored. `@goal:<id>` cites a goal in a
prompt and never binds one; see [Artifact Reference](#artifact-reference) for the
citation mechanics and [Goal Ledger](design-decisions.md#goal-ledger) for the storage
contract.

Not to be confused with a plan's `goal:` frontmatter field (one line of intent, no
record behind it), a task bead (agent work tracking), or agent status (liveness, not
outcomes).

## Instruction Bundle {#instruction-bundle}

_Also known as: instruction bundle._

An instruction bundle is the frozen per-invocation render of the project, home, and SASE
instructions for one agent invocation, built from `sase/memory/` plus the operator's
home memory layer and a provider directive. Each SASE root invocation gets one bundle,
delivered exactly once through an adapter-owned explicit channel; preview it with
`sase instructions render` and inspect what an agent received with
`sase instructions show NAME`. Successful preparation records the bundle bytes beside
its [Instruction Manifest](#instruction-manifest) under `instructions/`. It never
contains the committed `AGENTS.md` projection header.

## Instruction Manifest {#instruction-manifest}

_Also known as: instruction manifest._

An instruction manifest is the JSON sibling of an
[Instruction Bundle](#instruction-bundle): it records which sections were included and
their digests, plus the delivery status, so an agent's intended context can be compared
with what the provider actually loaded. Unlike a [Receipt](#receipt), which proves one
settled tool run, a manifest records intent, never observed delivery — use
`sase instructions verify` for the observed side.

## Job {#chop}

_Also known as: Chop, chops._

A job is one short, script-only unit of scheduler automation. The sase scheduler
supplies its context and applies configured cadence, triggers, guards, timeouts, and
deduplication; a structured result may request follow-up launches, which only the runner
performs. Chop remains an accepted lookup alias for older documentation, commands, and
legacy state paths.

## LLM Calls {#llm-calls}

LLM Calls is the Agents-tab card, in the Tools agent data deck, that shows normalized
provider tool-call artifacts (`tool_calls.jsonl` and compatible legacy rows). It is a
presentation/read-model term for what an LLM/provider did during an agent run, not an
execution record: named SASE tools and future ToolRuns are separate control-plane
concepts.

## Machine Tab {#machine-tab}

_Also known as: machine tabs._

A machine tab is the derived default [Agent Tab](#agent-tab) placement for agents a
remote machine owns, labeled `⌨ <alias>`; the default tab renders as the `⌨ local`
machine tab when machine tabs are on (`ace.agent_tabs.machine_tabs`). Machine tabs are
derived, never authored: `%tab:<alias>` is an ordinary named tab, distinct from
`⌨ <alias>`. The key is the owner's installation id, so renaming an alias relabels the
tab and keeps its selection and memory. A stale host's label turns amber and an invalid
or offline host's turns red.

## Macro {#macro}

_Also known as: xprompt._

Formerly called an xprompt. Triggered with `#foo` in agent prompts. Defined in a
sase/macros/ directory (.md or .yml file) or in ~/.config/sase/sase.yml (`macros`
field). Each use of a macro in a prompt is a macro invocation (smack).

## Macro Invocation {#macro-invocation}

_Also known as: smack, macro reference, macro ref._

A macro invocation (smack) is one `#name` or `#!name` use of a macro in prompt text,
with its arguments and modifiers: `#review(path=a)`, `#review:x`, `#review: text`,
`#flag+`, `#ns/name`, or a standalone `#!sync`. SASE expands or runs it before the agent
sees the prompt. The macro is the definition and the invocation is one use of it; a
prompt can hold zero or many. VCS workspace references such as `#gh:sase` and
`#git:home` are invocations of workspace workflows, and a project tag expands into one.
A `#` token that names no macro passes through as literal text, and one inside a literal
zone is not an invocation. Smack is short for sase macro invocation.

## Macro Memory {#macro-memory}

_Also known as: memory file, sase memory._

A flat SASE memory note exposed as a namespaced macro: `sase/memory/foo.md` expands with
`#memory/foo`, and the `memory/` prefix is required.

## Macro Part {#macro-part}

.md file -> single `prompt_part` step with the file's content.

## Macro Swarm {#macro-swarm}

A macro whose body contains top-level `---` segment separators outside fenced blocks and
fans out into one agent per segment at launch. Literal user prompts can also use `---`,
but those are generic multi-agent prompts rather than macro swarms.

## Macro Workflow {#macro-workflow}

.yml file -> multiple steps (`prompt_part`, `python`, `bash`, etc.).

## Memory Strand {#memory-strand}

One note inside a Memory Web, stored at `sase/memory/<web>/<slug>.md`. A strand body is
never inlined into a generated document; it is fetched on demand by Strand Keyword. A
project strand overrides a home strand with the same slug.

## Memory Web {#memory-web}

A memory web is a keyed note collection: one flat descriptor note
(`sase/memory/<web>.md`, marked `web: true`) plus a sibling directory of strand files.
The descriptor must not declare `type:` or `parent:`; a web's kind, not a rendering
declaration, decides its placement, so its body always renders in the generated
document's Memory Webs section and carries a roster naming every strand. Strand bodies
never inline, and are read on demand with `sase memory read <web>:<keyword>`.

## Named Proc {#named-proc}

A named proc is a supervised proc with a stable `proc_name` (`proc_role: "proc"`), with
durable output and lifecycle state. A monitor turn's command runs as a named proc named
after its member. A stand-alone `%proc` prompt unit is a named proc that belongs to no
agent or session, allocates no agent runner, and appears in the Agents tab as its own
proc node, counted separately from agents. A gate turn's execution proc
(`proc_role: "gate"`) does not make the gate turn a monitor turn. Formerly called a proc
shell.

## Nav Item {#nav-item}

_Also known as: navigation item._

A nav item is one selectable row in a nav section — a stop for row navigation such as
`j`/`k`. On the Agents tab, every sase node is a nav item; on the Services tab, every
service proc, oneshot, routine, and job row is; on the Artifacts tab, every entry in the
visible pane's list (an agent, stitch, Patch, bead, document, or file) is. A collapsed
grouping banner on the Agents tab or Patch pane is a nav item while collapsed, yet never
a node. Panel titles, expanded banners, headings, dividers, and empty-state rows are
chrome, not nav items, and a selected whole tribe panel (`❖`) is a selected nav section,
not a nav item.

## Nav Section {#nav-section}

_Also known as: navigation section._

A nav section is one panel in the left-side navigation column of a main TUI tab; each of
its selectable rows is a nav item. On the Agents tab, every agent tribe panel
(`@default`, `@<tribe>`, or the merged `All agents` panel) is a nav section; on the
Services tab, the Service Procs and Scheduled Routines panels are; on the Artifacts tab,
each pane's entry list (Agent, Commits, Patches, Beads, a document provider such as
Plans, or Files) is one, and only the visible pane's list shows. A nav section is a
whole panel: grouping banners, in-list headers and dividers (Beads `Tasks`, the Services
`── oneshots ──` divider), the Artifacts relation and Patch info panels, right-side
detail panels, and Admin Center lists are not nav sections.

## Node Panel {#node-panel}

The node panel is the Agents tab's left column of sase node rows: tribe panels divide
the active [Agent Tab](#agent-tab), one agent list per tribe, or one merged list at the
Merged and All-tabs layout levels. `Ctrl+S` collapses it into a slim node spine without
unmounting it, so j/k still move the selection and the identity header still follows it;
the spine and an info-row chip show the selected position and restore the panel.

## Oneshot Service Proc {#oneshot-service-proc}

_Also known as: oneshot, background command._

A oneshot service proc runs once to completion and is never restarted. Transient
oneshots are created at runtime by the TUI's `!` background commands or
`sase service proc run`; they run outside the sase service's process tree, so restarting
the sase service does not kill them. Distinct from a job, which a routine runs on a
schedule.

## Patch {#patch}

A Patch is SASE's local unit of change. Every PR created or managed by SASE is
associated with exactly one Patch, but a Patch may exist without a PR, represented by an
absent `PR:` field. Active Patches live in ProjectSpec `<key>.sase` (directory key
`<key>`; see Project, Repo, and Workspace); terminal ones (Submitted, Archived,
Reverted) live in `<key>-archive.sase`. Sections: NAME, DESCRIPTION, PARENT, PR, STATUS,
STITCHES, HOOKS, COMMENTS, MENTORS. Status lifecycle: WIP -> Draft -> Ready -> Mailed ->
Submitted.

## Proc {#proc}

_Also known as: procs._

A Proc is a durable background process SASE records, supervises, and can stream or kill.
Procs live in `~/.sase/procs/procs.jsonl` with combined output logs and are surfaced by
`sase proc` and the Procs tab in sase's TUI. Historical proc rows may use `command`,
`tui`, or `detached` kind values, but those names are compatibility labels rather than
permanent semantic categories. Runs of service procs carry a `service` marker; the Procs
tab hides them by default. A supervised proc with a stable name is a
[Named Proc](#named-proc). Distinct from a task bead, which is a work item, and from an
asyncio task.

## Project Tag {#project-tag}

_Also known as: macro project tag, project tags._

A project tag is the `+<project>` word naming the [Sase Project](#sase-project) an agent
runs in. It resolves by key, name, or alias, case-insensitively, against unique names,
then expands to the project's VCS macro ref and shares its backend. It is the default
spelling; `#gh:`/`#git:` remain for Patches, `owner/repo`, `@agent`, and new projects.
An anchored tag (first word on its line) must resolve. It renders in the project's
accent, like the chip.

## Prompt Stash {#prompt-stash}

_Also known as: stash._

A prompt stash is the per-user draft pile where sase's TUI parks prompt panes outside
prompt history: manual `Ctrl+S`/`gs` captures, restart stashes, and failed-launch
recovery rows. Stash rows keep their bundled pane order, frontmatter, cursor, project,
source, creation time, and pin. The stash surfaces as the Stash tab of the Prompts
overlay (`@`, `,@`, `Ctrl+G p`, the stash chip, empty `Ctrl+S`); on the Stash tab `@`
restores the newest draft, so `@@` pops the most recently stashed prompt. Rows
deliberately discarded from it move to [Stash Trash](#stash-trash) for bounded recovery
instead of permanent deletion.

## Raw Prompt {#raw-prompt}

The raw prompt is an agent's launch prompt after project tags and macro aliases are
canonicalized (`+sase` becomes a `#gh:` workspace reference and `#c` becomes `#commit`)
and before any macro invocation expands. It is saved as `raw_prompt.md`, shown on the
RAW PROMPT tab, and reused by restarts. It follows the submitted prompt
(`submitted_prompt.md`, the launch-boundary text before canonicalization) and precedes
the expanded prompt the model receives, from which directives are stripped. It is
unrelated to `sase prompt show -f raw` and to raw `<label>` placeholders.

## Receipt {#receipt}

A receipt is the machine-local proof that one named [Tool Catalog](#tool-catalog) entry
produced one settled [Tool Run](#tool-run) with one trustworthy
[Triage Verdict](#triage-verdict) on one exact fingerprint. The Rust core mints it only
after wrapper and triage settlement for an eligible run, and `sase tool receipt` reports
it (or exactly one typed refusal) without ever claiming a completion policy is met. An
explicitly opted-in prepared [Sase Monitor](#sase-monitor) completion may consult a
covering, unexpired receipt before committing an all-KNOWN/FLAKY tree; the receipt never
skips or reuses the execution itself.

## Reference Memory {#reference-memory}

_Also known as: reference memory._

A SASE memory declared by type: reference frontmatter, named in AGENTS.md with a
description, and fetched explicitly through an audited sase memory read. Author new
notes with type: reference. Legacy type: long still parses as reference. Reference
Memory is read on demand, unlike Core Memory.

## Required Plugin {#required-plugin}

_Also known as: required plugin._

A required plugin is a distribution listed under `plugins.required` in project config as
a PEP 508 requirement. A linked or sidecar checkout is not an install: SASE checks the
running environment's distributions. Every non-`builtin` `<plugin>@` prefix used in that
project — including Artifact Reference, file-hook, and Task Type `use:` values — must
appear in the list. `sase memory init` and `sase validate` fail closed when a required
plugin is missing; interactive surfaces may offer to install.

## Routine {#lumberjack}

_Also known as: Lumberjack, lumberjacks._

A routine is an independently supervised scheduler process that runs its configured jobs
concurrently on a fixed interval and records its own state and metrics. The sase
scheduler starts it and restarts it after crashes. Lumberjack remains an accepted lookup
alias for older documentation, commands, and legacy state paths.

## Sase Agent {#sase-agent}

_Also known as: agent._

A sase agent is an agent session or a single agent that does not belong to a session. It
owns an ordered sequence of sase turns, and its name never ends in `--<suffix>` because
that suffix is reserved for agent turns. A one-turn agent may share its turn name, while
a session uses the bare name for its container.

## Sase Agent Session {#sase-agent-session}

_Also known as: agent session._

A sase agent session is a sase agent whose agent turns run as a strictly sequential
chain. Its turns use `<session>--<suffix>` names. The first
`%id(<suffix>, session=<parent>)` attachment renames the original turn with its own
suffix and reserves the bare session name as the sase agent container, so a session
always has at least two turns. It was formerly called an agent family. It is distinct
from TUI sessions (`sase proc --session`), provider transcript sessions (`session_id`),
and question sessions.

## Sase Gate {#sase-gate}

_Also known as: gate._

A sase gate is a durable, command-backed request for one user decision, created when
work must pause for the user. Each gate is a bundle under
`~/.sase/interaction_requests/<kind>/<request-id>/` holding the hashed request, the
reviewed content, and the argv commands its options run; a notification row is only its
transport projection, so sase's TUI, Telegram, mobile, and `sase gate` all answer the
same bundle. An option query such as `(approve AND commit) OR reject` names the mutually
exclusive branches; answering selects a non-empty subset of exactly one branch, runs
those options' commands, and writes `response.json` once, while a gate's declared
actions are repeatable and never answer it. Typed kinds (plan, epic plan, question,
launch, task triage) have their own front doors; `sase gate create` builds a `custom`
one. A gate carrying a `turn` block is a gate turn and settles as `completed`, `failed`,
`timeout`, `stopped`, or `lost`; a gate with no `turn` block settles only as answered,
cancelled, or timed out. `sase gate wait` reports the latter and is for non-agent
callers — an agent observes a gate turn through the session it hands off to, never by
waiting. Unrelated to the pytest suite gate and `just check`'s lint gates.

## Sase Monitor {#sase-monitor}

_Also known as: monitor, monitor turn._

A sase monitor is a monitor turn that runs one long command under a detached supervisor,
so the command outlives the agent that started it. Starting one from inside an agent
hands off and kills that agent's turn, and an agent has at most one active monitor at a
time; monitor members are named `<session>--mon`, then `--mon-0`, `--mon-1`. A monitor
settles as `completed`, `failed`, `timeout`, `stopped`, or `lost`, and only the first
three launch the follow-up agent recorded by `--next`. Inspect monitors with
`sase monitor`.

## Sase Node {#sase-node}

_Also known as: node._

A sase node is one row of the Agents tab's agent tree: an agent clan node, an agent node
(with its member sase turn nodes), an agent step node — a workflow `python`, `bash`, or
`parallel` step — or a stand-alone named proc node. Every sase node is a nav item, but
nodes exist only on the Agents tab: Services and Artifacts nav items are not nodes.
Grouping banners (including selectable collapsed ones) and tribe-panel titles are not
nodes.

A node's status is the word its row shows, including render-time overlays such as
`FINALIZING`; a container node derives its status from its members, and an agent clan
node with exactly one running member node shows that node's status.

## Sase Project {#sase-project}

A sase project is a named unit of work registered with SASE. Existing repositories can
be added with `sase project add` or the New Project wizard; the wizard can also create a
repository through the provider. `sase project create` creates a repository and
registers the resulting project. A new VCS macro argument can also create a project:
`#git:<name>` accepts any valid project name, while `#gh:<org>/<repo>` requires an
existing GitHub repository. Its ProjectSpec is `~/.sase/projects/<key>/<key>.sase`,
where the directory key `<key>` is `<name>` for `#git` projects but `gh_<org>__<repo>`
for `#gh` projects (ex: `gh_sase-org__sase`); the user-facing name is the spec's
`PROJECT_NAME:` (ex: `sase`) or, if unset, the key. Projects have exactly two
user-facing states, enabled and disabled; onboarding leaves `PROJECT_STATE:` unset, so
new projects are enabled by default, and only an explicit disable changes that. The
system-managed `home` project remains hidden. Prompts name an existing project with a
[Project Tag](#project-tag) (`+<project>`). Directory keys, names, and aliases are
unique across projects and VCS types, compared case-insensitively.

## Sase Repo {#sase-repo}

A sase repo is any repository SASE knows: a project's primary repo, an artifact sidecar
repo such as `<project>--plans` or `<project>--research`, or a repo declared through
`repos.linked`.

## Sase Scheduler {#sase-scheduler}

_Also known as: scheduler, AXE._

The sase scheduler is the builtin service proc behind `sase scheduler` that runs SASE's
background automation: it starts one process per routine and restarts crashed routines,
and routines run jobs. The sase service owns the scheduler's process lifetime; the
scheduler owns only its routine/job tree. AXE is its former name and remains an accepted
alias.

## Sase Service {#sase-service}

_Also known as: service host._

The sase service is the per-machine host process (`sase service run`) that starts,
restarts, and stops that machine's service procs, with at most one per SASE home.
`sase service init` registers it as a platform unit — a systemd user unit on Linux, a
launchd LaunchAgent on macOS — so it starts at boot or login; without one,
`sase service start` runs it detached. systemd/launchd supervises the sase service
itself, never each service proc. Say 'service proc' for what it runs and 'platform unit'
for its registration; bare 'service' is ambiguous.

## Sase Turn {#sase-turn}

_Also known as: turn._

A sase turn is one executing member of a sase agent: an agent turn, a monitor turn, or a
gate turn. A sase agent is an ordered sequence of sase turns. Read the three kinds like
a chat transcript: an agent turn is the assistant speaking, a monitor turn is a tool
result arriving, and a gate turn is the human's move. Formerly called a sase shell. Not
a provider's internal round trips (`num_turns`) or a chat-history conversation turn.

## Sase Workspace {#sase-workspace}

_Also known as: workspace._

A sase workspace is a numbered clone of a project's primary repo, managed by the
workspace store and tracked in that project's `registry.json`. Each SASE agent claims
exactly one workspace until completion. Workspace directories are not repos. Linked-repo
clones materialized for a workspace are repo checkouts, not additional workspaces.

## Service Proc {#service-proc}

A service proc is a named proc the sase service owns, declared under `service.procs` by
core (builtin), a plugin's config layer, or the user, or created at runtime as a
transient oneshot. Its mode is `daemon` — kept running under its restart policy — or
`oneshot` — run once to completion. Control one with `sase service proc` or its
Services-tab nav item, which stays the same row across restarts; `enabled: false` in a
machine overlay keeps it off that machine. Every launch is a distinct durable Proc
carrying a `service` marker, hidden from the Procs tab and proc gear by default.

## Stash Trash {#stash-trash}

Stash Trash is the bounded, transactional recovery bin for drafts deliberately discarded
from the [Prompt Stash](#prompt-stash). It surfaces as the Stash tab's Trash view in the
Prompts overlay (the 🗑️ chip on the Stash tab, or `t`; `t`/`Esc` return to Stash),
newest-deleted-first with the deletion age visible, and restores move rows back to Stash
while the overlay stays open. It holds at most `ace.prompt_stash.trash_limit` entries
(default 100, an entry-count limit; zero disables recovery). Overflow evictions and
lowered-limit reconciliations permanently delete oldest-first and are always surfaced.
Successful unpinned stash restores never enter Trash, and history deletion remains
outside the overlay.

## Stitch {#stitch}

A stitch is the lightweight ordered change record inside a Patch's `STITCHES:` section.
Every VCS commit made through the tracked workflow has an associated numeric stitch, but
a stitch need not have a commit: proposals retain numeric-plus-letter IDs such as
`(2a)`. The `sase stitch create` command and real Git/Mercurial commits are still called
commits.

## Strand Keyword {#strand-keyword}

The `keyword:` a Memory Strand is addressed by, as `<web>:<keyword>`, together with any
`aliases:`. It is distinct from the strand's filename slug, which is its identity.

## Task Type {#task-type}

_Also known as: task type._

A task type is the required, plugin-extensible flavor of a task bead — `bug`, `ci`,
`feature`, `flake`, `memory`, the project-local `flag` type, and plugin slugs such as
`github`. It is distinct from the bead's issue type (`plan`, `phase`, `task`). New tasks
take `-T "task(<slug>)"` plus `-f/--field` values; the type is immutable after create.
The catalog is assembled from builtins, `sase_task_types` plugins, and `bead.task_types`
project config, then snapshotted to `sase/task_types.json` so generated instructions
stay a function of committed files and Required Plugin entries rather than whichever
optional plugins happen to be installed.

## Tool Catalog {#tool-catalog}

The Tool Catalog is the set of named tools (`check`, `test`, ...) declared under
`tools:` in the [Current Project](#current-project)'s own `sase/sase.yml`. Entries are
complete argv definitions that user, machine, plugin, and builtin config layers cannot
alter. `sase tool list` shows them; each execution becomes a [Tool Run](#tool-run).

## Tool Run {#tool-run}

A Tool Run is the durable, machine-local record `sase tool run` writes for one execution
of a [Tool Catalog](#tool-catalog) entry (or an ad-hoc argv): owner, lifecycle, exit or
signal, stage timeline, and before/after fingerprints. It records what a command did; it
is not the Agents-tab [LLM Calls](#llm-calls) card, and it is not a
[Sase Monitor](#sase-monitor) or [Proc](#proc) (those may own the run). The execution
runs in the foreground or is handed off to a monitor or proc that owns it
(`sase tool run -H` outside agents, `sase monitor start` inside them); either way the
run keeps one durable id that stays followable (`show -F`), waitable (`wait`), and
stoppable (`stop`) until it settles to an outcome or a typed uncertainty.

Its failed stages can carry [Failure Signature](#failure-signature)s and a
[Triage Verdict](#triage-verdict) without changing the recorded outcome.

## Triage Verdict {#triage-verdict}

A triage verdict summarizes the stored failure-item classes for one failed
[Tool Run](#tool-run): it distinguishes new failures from runs with only KNOWN or FLAKY
items, while preserving the command's original exit code. Missing evidence remains
UNKNOWN rather than being attributed to another agent.

## Usage Window {#usage-window}

_Also known as: usage-window._

A usage window is a provider-reported capacity allowance over a time interval, scoped to
all models or to a model/product subset, independently identified and measured, with a
reset time when the provider reports one. Claude examples include its five-hour
all-model window, weekly all-model window, and weekly Fable window.

Usage windows can overlap, and their percentages are independent: do not add, average,
or otherwise merge them. A window's duration is the size of the interval; time remaining
to reset is a separate clock-derived value.
