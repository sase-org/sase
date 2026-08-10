# CLI Reference

This page is a command index for the top-level `sase` CLI. It is meant for discovery and
routing: use it to find the surface that owns a workflow, then follow the links to the
detailed command, flag, or subsystem reference.

For exhaustive flag tables, see the
[configuration reference](configuration.md#cli-flags).

## Daily Operation

| Command                         | Purpose                                                                                                                                                                                          | Details                                               |
| ------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ | ----------------------------------------------------- |
| `sase ace`                      | Open ACE, the interactive control surface for Patches, live agents, notifications, and axe state.                                                                                                | [ACE TUI](ace.md)                                     |
| `sase run [PROMPT]`             | Launch an agent or workflow from a prompt, an xprompt reference, a workflow reference, history, or an editor buffer.                                                                             | [XPrompts](xprompt.md), [workflows](workflow_spec.md) |
| `sase agent list`               | List active and recent agents across projects.                                                                                                                                                   | [ACE Agents tab](ace.md#tab-system)                   |
| `sase agent show`               | Render one agent's detail panel by name.                                                                                                                                                         | [Agent attachments](agent_images.md)                  |
| `sase agent kill`               | Terminate a running agent.                                                                                                                                                                       | [ACE TUI](ace.md)                                     |
| `sase agent tribe`              | Set, clear, or list user-defined agent tribes used for grouping.                                                                                                                                 | [Agent tribes](agent_families.md#agent-tribes)        |
| `sase agent archive`            | Maintain dismissed-agent bundle summary indexes (`rebuild-index`, `verify`).                                                                                                                     | [ACE TUI](ace.md#agent-revival)                       |
| `sase agent artifacts`          | Inspect and migrate physical agent artifact storage layout.                                                                                                                                      | [Configuration](configuration.md#directory-sharding)  |
| `sase agent index`              | Manage the persistent agent artifact SQLite index (`status`, `rebuild`, `verify`, `gc`, `repair`).                                                                                               | [ACE TUI](ace.md)                                     |
| `sase agent names migrate-auto` | Backfill the permanent agent-name registry from legacy auto-generated names; pass `--force` to rerun.                                                                                            | [ACE TUI](ace.md)                                     |
| `sase agent sync`               | Import shared history and publish locally commit-eligible hoods; `--check --refresh` fetches fresh status, while `--retry-quarantined` and `--drop-retired` handle stopped publication requests. | [Agent hood synchronization](agents_sidecar.md)       |
| `sase chat list`                | List recent chat transcripts with sync provenance; filter with `-P/--provenance`, `-m/--machine`, and `-q/--query`.                                                                              | [ACE Chats pane](ace.md#chats-pane)                   |
| `sase chat show`                | Show one chat transcript by agent name, path, or basename; use `--format resume` for flattened turns or `--format response` for the latest response only.                                        | [ACE Chats pane](ace.md#chats-pane)                   |
| `sase prompt list`              | List, search, and filter previously submitted prompts (pretty table or JSON).                                                                                                                    | [Prompt history](prompt.md)                           |
| `sase prompt show`              | Print one prompt's exact text as raw, Markdown, or JSON.                                                                                                                                         | [Prompt history](prompt.md)                           |
| `sase prompt run`               | Replay a stored prompt by selector, optionally editing or re-prefixing it first.                                                                                                                 | [Prompt history](prompt.md)                           |
| `sase prompt save`              | Save a stored prompt as a reusable xprompt, or `export` it to stdout or a local file.                                                                                                            | [Prompt history](prompt.md), [XPrompts](xprompt.md)   |
| `sase prompt prune`             | Curate the prompt-history store with `delete`, `prune`, and read-only `doctor`/`stats`.                                                                                                          | [Prompt history](prompt.md)                           |
| `sase stitch list`              | List the primary, linked, and SDD repositories with branch, dirty, commit-count, and activity summaries.                                                                                         | [VCS](vcs.md#sase-stitch-list)                        |
| `sase stitch log`               | Show a primary/linked timeline; `--sdd` opts into separate SDD history in current or all-project scope.                                                                                          | [VCS](vcs.md#sase-stitch-log)                         |
| `sase gate create`              | Create a durable command-backed gate from a schema-versioned JSON specification.                                                                                                                 | [Notifications](notifications.md)                     |
| `sase gate show`                | Inspect a gate's branches, declared typed inputs, and repeatable actions without answering it.                                                                                                   | [Notifications](notifications.md#cli)                 |
| `sase gate answer`              | Answer a gate headlessly, including per-option typed input and explicit resume/restart of a partially executed branch.                                                                           | [Notifications](notifications.md#cli)                 |
| `sase gate act`                 | Run one gate-declared repeatable action without settling the gate.                                                                                                                               | [Notifications](notifications.md#cli)                 |
| `sase gate wait`                | Wait mechanically for a command-backed gate and return its terminal result.                                                                                                                      | [Notifications](notifications.md)                     |
| `sase notify`                   | Shortcut for `sase notify list`.                                                                                                                                                                 | [Notifications](notifications.md)                     |
| `sase notify create`            | Create a raw, non-privileged notification from JSON input.                                                                                                                                       | [Notifications](notifications.md)                     |
| `sase notify list`              | List recent notifications, optionally filtered by sender, tag, unread state, or query.                                                                                                           | [Notifications](notifications.md)                     |
| `sase notify show`              | Show one notification as Markdown or JSON.                                                                                                                                                       | [Notifications](notifications.md)                     |
| `sase task`                     | Shortcut for `sase task list`.                                                                                                                                                                   | [ACE Tasks tab](ace.md#tasks-tab)                     |
| `sase task list`                | List durable background tasks; filter by kind, session, project, tag, status, or query.                                                                                                          | [ACE Tasks tab](ace.md#tasks-tab)                     |
| `sase task run -- COMMAND`      | Run a durable command task; `--detached` makes it global, and `--wait` streams it and returns its exit code.                                                                                     | [ACE Tasks tab](ace.md#tasks-tab)                     |
| `sase task show ID`             | Show one task and its captured output; `--follow` streams until it finishes.                                                                                                                     | [ACE Tasks tab](ace.md#tasks-tab)                     |
| `sase task kill ID`             | Kill a running task by id or unique prefix; an already-terminal task is an unchanged no-op.                                                                                                      | [ACE Tasks tab](ace.md#tasks-tab)                     |
| `sase repro replay`             | Replay an Agents-tab reproduction bundle through the headless TUI harness and emit a verdict.                                                                                                    | [ACE TUI](ace.md#agents-tab-reproduction-bundles)     |
| `sase repro capture agents-tab` | Capture a commit-safe out-of-band Agents-tab bundle from current filesystem state.                                                                                                               | [ACE TUI](ace.md#agents-tab-reproduction-bundles)     |

`sase run` launches detached background agents that appear in the ACE Agents tab. It can
start from prompt text, xprompt or workflow references, the editor, or the
prompt-history picker, and multi-prompt input expands into sequential background
launches. ACE uses the same launch machinery when users start agents from the TUI.

`sase agent list -j` reports every live runner-slot waiter as `status: "QUEUED"`,
whether its threshold comes from the global cap or an authored `%wait(runners=N)`. Its
`runner_slot_queue_position`/`runner_slot_queue_size` rank the same waiters in the
capacity-aware display order used by ACE: eligible waiters first, then parked waiters by
nearest-opening threshold, with priority and request FIFO preserved inside each group.

`sase task` operates on durable background tasks: rows in `~/.sase/tasks/tasks.jsonl`
with combined output logs under `~/.sase/tasks/logs/`. There are three kinds: `tui` work
is run and mirrored by one ACE process; `command` work runs under a supervisor but is
attributed to a session; and `detached` work runs under a supervisor with no owning
session, so every CLI and TUI includes it in scope. `sase task run` creates `command` by
default, while `--detached` creates the global kind and is mutually exclusive with
`--session`.

The supervisor is independent of the submitting shell or TUI, so both `command` and
`detached` work survive TUI restarts and run with no TUI open. Use repeatable
`--kind command|tui|detached`, or the `--detached` list shorthand, to filter by kind.
The compact list markers are `⌘` for `command`, `▣` for `tui`, and `◆` for `detached`;
`sase task show` spells out the kind and describes detached ownership. Use
`sase task kill ID` to stop any active store-backed task. Retention keeps every pending
or running task plus the newest [`tasks.history_limit`](configuration.md#tasks) finished
ones. See the [ACE Tasks tab](ace.md#durable-background-tasks) for the full model and
the in-TUI equivalents.

Command groups with an exact `list` child default to that list view when invoked bare,
including `sase agent-cli`, `sase bead`, `sase chat`, `sase file`, `sase file-history`,
`sase file-hook`, `sase memory`, `sase notify`, `sase plugin`, `sase project`,
`sase prompt`, `sase skill`, `sase stitch`, `sase task`, `sase telemetry`, `sase var`,
`sase workspace`, and `sase xprompt`. Nested groups such as `sase agent tribe`,
`sase axe chop`, `sase axe lumberjack`, `sase memory agent-docs`, and `sase plan links`
follow the same rule.

The bare form is only the default view. When you need flags that belong to the list
command, keep the `list` subcommand explicit, for example `sase notify list -j`,
`sase memory list -j`, or `sase workspace list --json`.

## Work Tracking And Planning

| Command                                      | Purpose                                                                                                            | Details                                                           |
| -------------------------------------------- | ------------------------------------------------------------------------------------------------------------------ | ----------------------------------------------------------------- |
| `sase patch current`                         | Render the Patch associated with the current workspace.                                                            | [Patches](change_spec.md)                                         |
| `sase patch ref`                             | List, attach, or detach durable artifact references on a Patch; the bare command defaults to `ref list`.           | [Patch references](change_spec.md#refs)                           |
| `sase patch migrate-extension`               | Rename legacy `.gp` ProjectSpec files to the canonical `.sase` extension.                                          | [ProjectSpec](project_spec.md)                                    |
| `sase patch search`                          | Search and filter Patches with the query language.                                                                 | [Query language](query_language.md)                               |
| `sase patch sync-deltas`                     | Recompute the `DELTAS` field for a Patch from VCS state.                                                           | [Patches](change_spec.md)                                         |
| `sase init`                                  | Check and initialize config, memory, repositories, and skills for the current project.                             | [Initialization](init.md)                                         |
| `sase init --all --check`                    | Check every enabled main project without writing; report one aggregate status.                                     | [Initialization](init.md)                                         |
| `sase init --all --yes`                      | Initialize every enabled main project without generic prompts; sidecar creation still asks.                        | [Initialization](init.md)                                         |
| `sase memory` / `sase memory list`           | Show loaded, referenced, available, and missing memory files.                                                      | [Memory](memory.md#inspect-context)                               |
| `sase memory agent-docs list`                | Inventory project, home, and chezmoi `AGENTS.md` files plus nearby provider shims.                                 | [Initialization](init.md#agent-documents)                         |
| `sase memory read`                           | Agent-side read of one long-term memory file with an attributable audit event.                                     | [Memory](memory.md#audited-reads)                                 |
| `sase memory write`                          | Agent-side proposal for human-reviewed long-term memory; `--notify` can add an inbox item.                         | [Memory](memory.md#propose-memory)                                |
| `sase memory review`                         | Human listing, inspection, approval, editing, or rejection of pending memory proposals.                            | [Memory](memory.md#review-proposals)                              |
| `sase memory log`                            | Summarize audited memory reads; `--include proposals` also shows proposal and review events.                       | [Memory](memory.md#audited-reads)                                 |
| `sase memory init`                           | Refresh home and SASE-managed project memory; copy existing AGENTS.md files to provider instructions.              | [Initialization](init.md#memory-initialization)                   |
| `sase init memory`                           | Alias for `sase memory init`.                                                                                      | [Initialization](init.md#memory-initialization)                   |
| `sase repo init`                             | Initialize configured sidecars, generated guides, config, and repository ignores.                                  | [Initialization](init.md)                                         |
| `sase init repo`                             | Alias for `sase repo init`.                                                                                        | [Initialization](init.md)                                         |
| `sase repo path REPO`                        | Print a primary or sidecar path; `--ensure` materializes the selected sidecar.                                     | [SDD Storage](sdd_storage.md)                                     |
| `sase plan links [list]`                     | Inspect prompt/plan artifact links; bare `links` defaults to `list`.                                               | [SDD](sdd.md)                                                     |
| `sase plan links repair`                     | Infer and optionally write missing bidirectional SDD links.                                                        | [SDD](sdd.md)                                                     |
| `sase plan links validate`                   | Validate SDD artifact links.                                                                                       | [SDD](sdd.md)                                                     |
| `sase plan search`                           | Search or browse tale, epic, prompt, and research artifacts.                                                       | [SDD](sdd.md)                                                     |
| `sase plan show [TARGET]`                    | Resolve any plan reference form and render its details, or JSON/raw output.                                        | [SDD](sdd.md#plan-frontmatter-schema-and-validation)              |
| `sase plan validate PLAN_FILE`               | Validate one plan against the schema selected by its authored `tier`; `--explain` prints authoring guidance.       | [SDD](sdd.md#plan-frontmatter-schema-and-validation)              |
| `sase bead onboard`                          | Print the bead quick-start guide.                                                                                  | [Beads](beads.md)                                                 |
| `sase bead init`                             | Initialize bead storage for the current project.                                                                   | [Beads](beads.md#storage)                                         |
| `sase bead create`                           | Create plan, epic, phase, or standalone task issues.                                                               | [Beads](beads.md#cli-commands)                                    |
| `sase bead +1`                               | Corroborate an existing task with one reporter's independent evidence.                                             | [Beads](beads.md#task-corroboration-1)                            |
| `sase bead list`                             | List bead issues by status, type, tier, or creation date.                                                          | [Beads](beads.md#cli-commands)                                    |
| `sase bead search`                           | Search bead IDs, titles, notes, plan paths, metadata, and lifecycle fields; `--regex` enables regular expressions. | [Beads](beads.md#sase-bead-search-query)                          |
| `sase bead pages`                            | Refresh generated bead pages or print one bead's hosted page URL.                                                  | [Beads](beads.md#bead-pages)                                      |
| `sase bead ready`                            | Show task beads marked ready whose dependencies are closed.                                                        | [Beads](beads.md#standalone-task-workflow)                        |
| `sase bead blocked`                          | Show issues blocked by active dependencies.                                                                        | [Beads](beads.md#dependencies)                                    |
| `sase bead show`                             | Show one issue.                                                                                                    | [Beads](beads.md#cli-commands)                                    |
| `sase bead update` / `open` / `close` / `rm` | Mutate issue metadata or lifecycle state.                                                                          | [Beads](beads.md#cli-commands)                                    |
| `sase bead dep add`                          | Add an issue dependency.                                                                                           | [Beads](beads.md#dependencies)                                    |
| `sase bead sync`                             | Regenerate the JSONL projection from canonical events and stage bead state.                                        | [Beads](beads.md#sync-mechanism)                                  |
| `sase bead stats` / `doctor`                 | Inspect project statistics or bead-store health.                                                                   | [Beads](beads.md#rust-backend)                                    |
| `sase bead work`                             | Launch one or more plan, epic, or task targets in order.                                                           | [Beads](beads.md#sase-bead-work-target)                           |
| `sase project list`                          | List enabled projects by default, or inspect disabled/internal backing records with `--state`.                     | [Project lifecycle](project_spec.md#project-lifecycle)            |
| `sase project show`                          | Show lifecycle, workspace, launchability, and warning details for one project.                                     | [Project lifecycle](project_spec.md#project-lifecycle)            |
| `sase project enable` / `disable`            | Apply the normal user-facing `PROJECT_STATE` transitions under lock.                                               | [Project lifecycle](project_spec.md#project-lifecycle)            |
| `sase project set-state`                     | Set a lifecycle or internal backing state under the ProjectSpec lock.                                              | [Project lifecycle](project_spec.md#project-lifecycle)            |
| `sase project alias`                         | List, add, remove, or clear `PROJECT_ALIASES` under the ProjectSpec lock.                                          | [Project names](project_spec.md#project-names-and-aliases)        |
| `sase plan` / `sase plan list`               | Show pending proposals, recent approvals, and inferred rejected archived proposals.                                | [XPrompt directives](xprompt.md#plan-directive)                   |
| `sase plan approve`                          | Approve one pending plan by ID or prefix; `--kind` chooses approve/commit/epic/tale.                               | [Plan approval pipeline](agent_families.md)                       |
| `sase plan propose`                          | Submit a plan file for approval from the plan skill path.                                                          | [XPrompt directives](xprompt.md#plan-directive)                   |
| `sase plan reject`                           | Reject one pending plan by ID or prefix, then attempt planner cleanup when found.                                  | [XPrompt directives](xprompt.md#plan-directive)                   |
| `sase plan search`                           | Search resolved-store SDD plans and the machine-local plan archive by literal text and metadata.                   | [SDD](sdd.md#how-sdd-works)                                       |
| `sase plan show`                             | Resolve a path, `plans:` reference, pending-approval selector, slug, or bead id to one plan and show it.           | [SDD](sdd.md#how-sdd-works)                                       |
| `sase plan validate`                         | Validate one explicit plan path using its authored `tale` or `epic` tier, with human or JSON diagnostics.          | [SDD](sdd.md#plan-frontmatter-schema-and-validation)              |
| `sase launch request`                        | Register a launch gate; agent callers wait for a deterministic terminal JSON outcome.                              | [Agent groups](agent_families.md#agent-initiated-family-launches) |
| `sase launch approve` / `reject`             | Resolve a pending launch request by request id, notification id, or unique prefix.                                 | [Agent groups](agent_families.md#agent-initiated-family-launches) |
| `sase questions`                             | Ask structured user questions from the questions skill path.                                                       | [XPrompt directives](xprompt.md#directives)                       |

Patches are PR-sized review records. SDD stores durable prompt and planning artifacts.
Beads add git-portable dependency tracking and executable epics on top of those
artifacts.

`sase project` defaults to `sase project list`, and `sase project list` defaults to
enabled true projects. Use `sase project list --state all --json` to inspect disabled
projects and internal `sibling` backing records, `sase project disable <project>` to
hide a dormant project from default launch views, and `sase project enable <project>` to
make it launchable again. Disabling refuses projects with live `RUNNING` claims or
active artifact markers unless `--force` is passed. Legacy active/inactive values and
the deprecated lifecycle command aliases remain read-compatible. ACE's **Projects** tab
(in the SASE Admin Center, opened with `#`) provides the interactive counterpart,
including marking multiple projects, editing a ProjectSpec in `$EDITOR`, and deleting
obsolete SASE project directories after confirmation. There is no CLI delete subcommand;
full project-directory deletion is only available from ACE's Projects tab and removes
state under `~/.sase/projects/`, not workspace checkouts.

`sase project alias list [PROJECT] [-j|--json]`, `add PROJECT ALIAS`,
`remove PROJECT ALIAS`, and `clear PROJECT` manage ProjectSpec aliases. The ACE Projects
sub-tab (in the SASE Admin Center, opened with `#`) also displays aliases, includes them
in filtering, and opens an alias editor with `A`. Alias refs are accepted in
launch-bound VCS workspace tags, but prompt history, agent metadata, and artifacts use
the canonical directory-key project name. ProjectSpecs may also carry `PROJECT_NAME` as
the primary user-facing name. For example, the GitHub provider can create
`PROJECT_NAME: foo` and then `PROJECT_NAME: foo_1` for distinct `owner/foo` repositories
while keeping stable canonical project records. Existing auto-aliased GitHub projects
remain valid and keep resolving through `PROJECT_ALIASES`.

Enabled-only true-project discovery is also the default for launch pickers, Patch
searches, project-local xprompt catalogs, broad mobile helper catalogs, and all-known
bead helper reads. Internal sibling backing records are hidden from those surfaces and
support configured linked repositories. Agents prepare one through `/sase_repo`; the
underlying audited open infers the host project and workspace from cwd. Agent-history
views that need older artifacts opt into all project states explicitly. An explicitly
typed known-project VCS ref is a launch-time exception: it re-enables a disabled project
before claiming a workspace. A checkout cwd or mobile `project` value is only
prompt-resolution context, not a workspace ref; without an explicit ref, a bare prompt
defaults to `#git:home`. Direct low-level claims against a disabled ProjectSpec remain
blocked until the project is enabled.

`sase plan` defaults to `sase plan list`. The dashboard has Proposed, Approved, and
Rejected sections; use repeatable `-s/--status` options to select sections, `-n/--limit`
to set each history section's size (`0` is unlimited), and `-t/--tier` to filter by
plan-file tier. Proposed rows are never limited and are the actionable rows; each
includes an `id_prefix`, agent, project, provider/model, plan path, and response
directory. Pass that prefix to `sase plan approve <prefix>` or
`sase plan reject <prefix>`. If the selector is omitted, exactly one pending proposal
must exist. When `--kind` is omitted, approval follows the plan's authored `tier`; an
explicit kind overrides it. The Rejected section is inferred from archived proposal
files that are not represented by the proposed or approved state; it is a history aid,
not the selector source for new actions. The approval kind is the workflow choice:
`approve` runs the coder without asking the runner to commit an SDD plan, `tale` commits
the plan as an SDD tale and then runs the coder, `epic` commits the matching SDD tier
and launches the bead follow-up, and `commit` records the approved plan in SDD without
launching a coder. Use `-m/--model` to pick the follow-up agent's model. Use
`-p/--prompt` to add extra coder instructions for the `approve` and `tale` paths. Tale
and epic approvals validate against their target schema before writing a response; a
failure prints the diagnostics and expected schema and leaves the proposal pending for
retry. `sase plan reject` writes the rejection response first, then uses the same
durable cleanup path as the TUI no-feedback rejection action when the matching planner
row is still discoverable. If cleanup cannot find or kill the row, the CLI reports that
separately after the plan has already been rejected.

`sase plan search [QUERY]` searches plans in the resolved SDD store (the `repo` source)
and the machine-local `~/.sase/plans/` archive. Omit the query to browse with metadata
filters. Compact and Markdown output group SDD-store matches above local matches; JSON
and full output keep ranked result order with SDD-store matches prioritized over
otherwise-similar local matches. Useful filters include `--kind`, `--status`,
`--source`, `--since`, `--until`, `--sort`, and `--format json|markdown` for
agent-friendly output.

`sase plan show [TARGET]` resolves any way a user can name a plan to exactly one plan
and renders it. In `-t auto` (the default), TARGET is tried against five rungs in order
and the first definitive match wins: `path` (an existing file, absolute or
cwd-relative), `ref` (a `plans:` reference, a legacy marker path, or a month-drifted
reference, Rust resolved), `proposal` (a pending-approval notification id or unique
prefix), `name` (a corpus slug or `<shard>/<slug>` lookup, with or without `.md`), and
`bead` (a bead id whose `design` field points at a plan). Pass `-t/--target` to force
one rung with no fallthrough. Omit TARGET to show the sole visible pending plan
proposal, exactly as `sase plan approve`/`reject` treat an omitted selector. Every
ambiguity prints its candidates as re-runnable `plans:` references and every miss prints
close-match suggestions; neither guesses. `-f/--format` selects `full` (the default
section-structured detail view, matching the ACE TUI's PLAN lane), `compact` (the same
row `sase plan search` prints), `json` (a schema-versioned envelope), or `raw` (the plan
file's exact text, for piping). A plan that fails validation still renders in full with
its diagnostics shown and exits `0`; only a missed, ambiguous, or unreadable target
exits `1`. `-w/--wrap` controls goal/phase/diagnostics prose wrapping, and `-c/--color`
matches `sase bead show`.

`sase plan validate PLAN_FILE` reads the required `tier: tale|epic` property and
validates exactly one path without a project or agent context. It reports every schema
problem in one run and prints the expected tier schema plus a minimal valid example on
failure. Use `-e/--explain` for tier-specific authoring guidance, `-j/--json` for the
stable machine-readable envelope, or `-q/--quiet` to suppress the successful human
summary. The removed `-t/--tier` option is now invalid command usage. A valid plan exits
0, a validation failure exits 1, and invalid command usage exits 2.

## Automation

| Command                          | Purpose                                                            | Details                                            |
| -------------------------------- | ------------------------------------------------------------------ | -------------------------------------------------- |
| `sase axe start`                 | Request running state and start the orchestrator and lumberjacks.  | [Axe](axe.md)                                      |
| `sase axe stop`                  | Request stopped state and stop the orchestrator and lumberjacks.   | [Axe](axe.md#cli-commands)                         |
| `sase axe ensure`                | Start a missing orchestrator unless axe was explicitly stopped.    | [Axe recovery](axe.md#watchdog-and-recovery)       |
| `sase axe ensure install`        | Install and enable the optional user-systemd timer.                | [Axe recovery](axe.md#watchdog-and-recovery)       |
| `sase axe ensure uninstall`      | Disable and remove the optional user-systemd timer.                | [Axe recovery](axe.md#watchdog-and-recovery)       |
| `sase axe status [--json]`       | Inspect one read-only whole-system snapshot in human or JSON form. | [Axe status](axe.md#whole-system-status)           |
| `sase axe chop list`             | List configured chops with status; `-a` adds scripts.              | [Axe chops](axe.md#chop-fields)                    |
| `sase axe chop doctor`           | Diagnose configured/available chops and Telegram setup.            | [Axe chops](axe.md#chop-fields)                    |
| `sase axe chop run <name>`       | Run one chop in the foreground.                                    | [Axe chops](axe.md#script-chops)                   |
| `sase axe lumberjack list`       | List configured lumberjacks.                                       | [Axe lumberjacks](axe.md#default-lumberjacks)      |
| `sase axe lumberjack run <name>` | Run one lumberjack in the foreground for debugging.                | [Axe lumberjacks](axe.md#lumberjack-configuration) |
| `sase axe lumberjack status`     | Show lumberjack process status.                                    | [Axe](axe.md)                                      |
| `sase axe maintenance enter`     | Pause scheduled lumberjack ticks with a recorded reason.           | [Maintenance mode](axe.md#maintenance-mode)        |
| `sase axe maintenance exit`      | Resume scheduled lumberjack ticks.                                 | [Maintenance mode](axe.md#maintenance-mode)        |
| `sase axe maintenance status`    | Inspect the maintenance marker.                                    | [Maintenance mode](axe.md#maintenance-mode)        |

Axe runs scheduled hooks, mentors, comment polling, workflow checks, `%wait` dependency
resolution, cleanup, and error digests. ACE starts axe automatically unless launched
with `sase ace --no-axe`.

## Prompt And Workflow Authoring

| Command                          | Purpose                                                                           | Details                                                                                     |
| -------------------------------- | --------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------- |
| `sase xprompt expand`            | Expand xprompt references in prompt text, with optional trace output.             | [XPrompt reference syntax](xprompt.md#reference-syntax)                                     |
| `sase xprompt explain`           | Dry-run a workflow and show the execution plan.                                   | [Workflows](workflow_spec.md)                                                               |
| `sase xprompt list`              | Emit the structured xprompt catalog as JSON.                                      | [XPrompt catalog](xprompt.md#cli-subcommands)                                               |
| `sase xprompt graph`             | Generate a workflow DAG as Mermaid or text.                                       | [Workflow graphing](xprompt.md#cli-subcommands)                                             |
| `sase xprompt catalog`           | Render visible xprompts to a formatted PDF catalog.                               | [XPrompt catalog](xprompt.md#cli-subcommands)                                               |
| `sase xprompt show`              | Show one xprompt definition with properties, provenance, and syntax highlighting. | [XPrompt show](xprompt.md#sase-xprompt-show)                                                |
| `sase lsp`                       | Start the xprompt language server over stdio.                                     | [Editor integration](editor.md#language-server)                                             |
| `sase editor helper-bridge`      | JSON helper operations for editor integrations.                                   | [Editor helper bridge](editor.md#helper-bridge)                                             |
| `sase file list`                 | Emit JSON filesystem completion candidates.                                       | [Editor completion commands](configuration.md#sase-file)                                    |
| `sase file-history list`         | Emit recently referenced files for editor completion.                             | [Editor completion commands](configuration.md#sase-file-history)                            |
| `sase file-history delete`       | Remove one path from the file-reference history.                                  | [Editor completion commands](configuration.md#sase-file-history)                            |
| `sase skill` / `sase skill list` | Inspect generated skill sources, provider targets, and deployed-file drift.       | [Initialization](init.md#skill-initialization), [bundled skills](xprompt.md#bundled-skills) |
| `sase skill init`                | Generate and deploy agent skill files from xprompt source templates.              | [Initialization](init.md#skill-initialization), [bundled skills](xprompt.md#bundled-skills) |
| `sase skill log`                 | Summarize or inspect audited generated skill-use events.                          | [Skill field](xprompt.md#skill-field)                                                       |
| `sase skill use`                 | Agent-side audit event recording that a generated skill was used.                 | [Skill field](xprompt.md#skill-field)                                                       |
| `sase init skills`               | Compatibility alias for `sase skill init`.                                        | [Initialization](init.md#skill-initialization)                                              |

Use `#name(...)` for inline xprompt expansion and `#!workflow(...)` for standalone
workflow references. Workspace references such as `#git:<project>` and plugin-provided
references are resolved before the prompt or workflow runs.

## Review And Delivery

| Command         | Purpose                                                                 | Details                                 |
| --------------- | ----------------------------------------------------------------------- | --------------------------------------- |
| `sase commit`   | Dispatch a commit, proposal, or PR through the configured VCS provider. | [Commit workflows](commit_workflows.md) |
| `sase revert`   | Revert a Patch by pruning its change and archiving its diff.            | [Commit workflows](commit_workflows.md) |
| `sase restore`  | Restore a reverted Patch by reapplying its archived diff.               | [Commit workflows](commit_workflows.md) |
| `sase comments` | Preview mentor comments from JSON with syntax-highlighted code context. | [Mentors](mentors.md)                   |

Delivery commands delegate to the VCS and workspace provider layers, so the same command
surface can support plain git, GitHub pull requests, and other provider plugins.

## Operations And Diagnostics

| Command                             | Purpose                                                                                                                                                                                                                           | Details                                                                                                              |
| ----------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------- |
| `sase doctor`                       | Run read-only install, config, provider, project, and state diagnostics for support.                                                                                                                                              | [Doctor support reports](#doctor-support-reports)                                                                    |
| `sase config layers`                | Show the configuration merge chain.                                                                                                                                                                                               | [Configuration](configuration.md)                                                                                    |
| `sase config show`                  | Dump the final merged configuration, optionally filtered by key.                                                                                                                                                                  | [Configuration](configuration.md)                                                                                    |
| `sase config mentor-match`          | Trace mentor profile matching for a Patch.                                                                                                                                                                                        | [Mentors](mentors.md)                                                                                                |
| `sase file-hook` / `file-hook list` | List effective post-commit/artifact file hooks, filters, commands, and contributing config layers.                                                                                                                                | [File hooks](configuration.md#file_hooks)                                                                            |
| `sase core health`                  | Check that the required `sase_core_rs` extension is loadable and working.                                                                                                                                                         | [Rust backend](rust_backend.md)                                                                                      |
| `sase validate`                     | Run portable memory/repo/skills initialization checks plus SDD frontmatter and agents-sidecar prompt archive validation.                                                                                                          | [Initialization](init.md), [SDD](sdd.md)                                                                             |
| `sase telemetry cleanup-test-data`  | Preview or remove telemetry rows carrying known exact test labels; deletion requires `-y`.                                                                                                                                        | [Telemetry](telemetry.md#sase-telemetry-cleanup-test-data)                                                           |
| `sase telemetry health`             | Run subsystem health assessment.                                                                                                                                                                                                  | [Telemetry](telemetry.md)                                                                                            |
| `sase telemetry list`               | Display the debugging and health metric catalog.                                                                                                                                                                                  | [Telemetry](telemetry.md)                                                                                            |
| `sase telemetry snapshot`           | Query current metric values from the local store.                                                                                                                                                                                 | [Telemetry](telemetry.md)                                                                                            |
| `sase telemetry status`             | Show local telemetry store and flusher status.                                                                                                                                                                                    | [Telemetry](telemetry.md)                                                                                            |
| `sase version`                      | Show the local `sase`, `sase-core-rs`, and installed plugin package inventory for this runtime.                                                                                                                                   | [Runtime inventory](configuration.md#sase-version)                                                                   |
| `sase plugin` / `plugin list`       | Browse the plugin catalog, marking built-in, community, installed, latest, and `↑` update indicators.                                                                                                                             | [Plugin catalog](plugins.md#plugin-catalog-sase-plugin-list-sase-plugin-show)                                        |
| `sase plugin show`                  | Show one plugin's detail panel: install status, latest version, repository, topics, and metadata.                                                                                                                                 | [Plugin catalog](plugins.md#plugin-catalog-sase-plugin-list-sase-plugin-show)                                        |
| `sase plugin install`               | Install a plugin into sase's own uv tool environment, resolving the name through the catalog.                                                                                                                                     | [Installing and updating plugins](plugins.md#installing-and-updating-plugins-sase-plugin-install-sase-plugin-update) |
| `sase plugin update`                | Upgrade one installed plugin (or every plugin with `-a`), leaving sase core pinned.                                                                                                                                               | [Installing and updating plugins](plugins.md#installing-and-updating-plugins-sase-plugin-install-sase-plugin-update) |
| `sase plugin uninstall`             | Remove one installed plugin from sase's own uv tool environment, preserving core and other plugins.                                                                                                                               | [Removing a plugin](plugins.md#removing-a-plugin-sase-plugin-uninstall)                                              |
| `sase update`                       | Upgrade sase and all installed plugins together; registry packages via `uv tool upgrade`, editable/dev installs via git fast-forward. `-n` previews, `-j` emits JSON.                                                             | [Updating sase and plugins](plugins.md#updating-sase-and-plugins-sase-update)                                        |
| `sase logs`                         | Collect and package agent run logs for a date range.                                                                                                                                                                              | [Configuration CLI flags](configuration.md#sase-logs)                                                                |
| `sase revive-log`                   | Inspect the agent-revival audit log (start / success / failure events).                                                                                                                                                           | [Agent revival audit log](troubleshooting/agent-revival.md)                                                          |
| `sase artifact` / `artifact list`   | List indexed artifacts with kind, project, agent, `--since`, `--unused`, and query filters; bare `sase artifact` defaults to `list`. Aliased as `sase artifact-file`. ACE browses the same index under Artifacts → Files → Other. | [Files → Other pane](ace.md#other-pane) · [Configuration CLI flags](configuration.md#sase-artifact)                  |
| `sase artifact create`              | Copy an explicit file into persistent agent artifact storage and print its durable `file:` ref; agent-only (`SASE_AGENT=1`).                                                                                                      | [Agent attachments](agent_images.md#explicit-artifact-contract)                                                      |
| `sase artifact doctor`              | Report artifact-index health, including VCS reference and provenance counts; `-f` backfills `sha256`/`size_bytes`/`mime_type` and `-v` re-hashes stored files and materializes VCS-backed rows.                                   | [VCS-backed artifact files](agent_images.md#vcs-backed-artifact-files)                                               |
| `sase artifact open`                | Resolve any artifact reference, including generated bead and agent pages, and open it with the viewer matching its kind and mime type.                                                                                            | [Configuration CLI flags](configuration.md#sase-artifact)                                                            |
| `sase artifact path`                | Print the single absolute filesystem path a reference resolves to, materializing VCS-backed rows on demand.                                                                                                                       | [Configuration CLI flags](configuration.md#sase-artifact)                                                            |
| `sase artifact prune`               | Plan retention with durable-reference and consumption protection; `--apply` moves selected automatic rows into restorable trash and refuses if a required protection source is unavailable.                                       | [Store lifecycle](agent_images.md#store-lifecycle)                                                                   |
| `sase artifact reclaim`             | Plan conversion of stored automatic rows to verified VCS-backed identities; consumed and durably referenced rows stay protected, and mutation requires `--apply`.                                                                 | [Store lifecycle](agent_images.md#store-lifecycle)                                                                   |
| `sase artifact show`                | Show one artifact reference's metadata, resolution report, and consumption summary, or a JSON envelope with `-j`.                                                                                                                 | [Configuration CLI flags](configuration.md#sase-artifact)                                                            |
| `sase artifact stats`               | Report artifact-store economics, protection-source counts and availability, trash occupancy, and the default retention plan.                                                                                                      | [Store lifecycle](agent_images.md#store-lifecycle)                                                                   |
| `sase artifact trash`               | List, permanently purge, or restore entries in the restorable artifact trash.                                                                                                                                                     | [Configuration CLI flags](configuration.md#sase-artifact)                                                            |
| `sase agent prompts`                | Browse and validate the canonical agents-sidecar prompt archive. `show` prints the archived Markdown document, and `migrate --write` moves historical plans-sidecar prompts into `prompts/<YYYYMM>/`.                             | [Agent Hood Synchronization](agents_sidecar.md#prompt-and-artifact-archive)                                          |
| `sase agent-cli` / `agent-cli list` | Inventory supported coding-agent CLIs with versions, install methods, and update markers.                                                                                                                                         | [Agent providers](agent_providers.md#inventory-and-updates)                                                          |
| `sase agent-cli update`             | Update selected agent CLIs (or every safe candidate with `-a`); `-n` previews commands and skips.                                                                                                                                 | [Agent providers](agent_providers.md#inventory-and-updates)                                                          |
| `sase agent-cli install`            | Install agent CLIs from the install script their provider declares, after showing the URL, SHA-256 digest, command, and target; needs `-y` or an interactive confirmation, and `-n` previews without executing.                   | [Agent providers](agent_providers.md#inventory-and-updates)                                                          |
| `sase var` / `sase var list`        | Display the current agent's JSON-shaped output variables as canonical blocks or JSON.                                                                                                                                             | [XPrompt variables](xprompt.md#cross-agent-output-variables)                                                         |
| `sase var set`                      | Attach named string or structured JSON output variables from assignments, literal text, files, or stdin.                                                                                                                          | [XPrompt variables](xprompt.md#cross-agent-output-variables)                                                         |
| `sase path`                         | Print well-known paths such as schemas and xprompt directories.                                                                                                                                                                   | [Configuration CLI flags](configuration.md#sase-path)                                                                |
| `sase repo list`                    | Show primary, sidecar, linked, and opened external repos; use `--all` or `--json` for cross-project and clone-matrix views.                                                                                                       | [Configuration CLI flags](configuration.md#sase-repo)                                                                |
| `sase repo log`                     | Summarize the durable repository-open audit log, with repo, agent, workspace, event-ID, and JSON filters.                                                                                                                         | [Configuration CLI flags](configuration.md#sase-repo)                                                                |
| `sase repo open`                    | Open an inventory repo, another SASE project, or `gh:owner/repo` external in the inferred workspace, then print its path.                                                                                                         | [Configuration CLI flags](configuration.md#sase-repo)                                                                |
| `sase workspace list`               | List one project's registry or use `--all` for the cross-project workspace inventory.                                                                                                                                             | [Workspace provider](workspace.md)                                                                                   |
| `sase workspace path`               | Print the checkout path for a workspace number.                                                                                                                                                                                   | [Workspace provider](workspace.md)                                                                                   |
| `sase workspace cleanup`            | Remove stale unclaimed managed checkouts older than the configured TTL.                                                                                                                                                           | [Workspace provider](workspace.md)                                                                                   |
| `sase workspace repair`             | Reconcile the workspace registry with the filesystem.                                                                                                                                                                             | [Workspace provider](workspace.md)                                                                                   |
| `sase workspace migrate`            | Opt-in move of adjacent checkouts to a managed root, with optional symlink transition and finalization.                                                                                                                           | [Workspace provider](workspace.md)                                                                                   |
| `sase mobile gateway start`         | Start the workstation-hosted mobile gateway.                                                                                                                                                                                      | [Mobile gateway](mobile_gateway.md)                                                                                  |
| `sase mobile agent-bridge`          | Fixed JSON bridge used by the mobile gateway for agent operations.                                                                                                                                                                | [Mobile gateway](mobile_gateway.md)                                                                                  |
| `sase mobile helper-bridge`         | Fixed JSON bridge used by the mobile gateway for workflow helper operations.                                                                                                                                                      | [Mobile gateway](mobile_gateway.md)                                                                                  |

The `sase artifact show`, `path`, and `open` commands take a logical reference without a
leading `@`, for example `sase artifact show file:default:<digest>`. Add the sigil when
embedding the same reference in a launch prompt:
`sase run "review @file:default:<digest>"`. This bare-CLI/`@`-in-prompts rule also
applies to document roles, chats, beads, agents, commits, and bugs. `path` accepts only
references with a filesystem identity; `open` can also open a bug in a browser but
rejects commits.

`stats`, `prune`, `reclaim`, and `trash` are the store's lifecycle commands, and they
are deliberately staged: `stats` only reports, `prune` and `reclaim` print a plan and
change nothing unless `--apply` is passed, and every removal either of them makes moves
the stored bytes **and** the complete index row into a restorable trash under
`~/.sase/artifacts/trash/`. `sase artifact trash restore` puts an entry back; only
`sase artifact trash purge` deletes permanently, and without `-a/--all` it purges only
entries older than `artifacts.retention.trash_grace_days`. Trashed bytes still occupy
disk until that purge runs. Explicit artifacts, artifacts a ProjectSpec, plan, bead, or
research document references, artifacts recorded in the consumption ledger, and the
newest capture of every label are never selected; if a required protection source cannot
be read, `--apply` refuses rather than under-protecting. See
[Store Lifecycle](agent_images.md#store-lifecycle).

`sase artifact list` inventories only the persistent artifact-file index; it is not a
catalog of every reference kind and it does not browse the agents-sidecar prompt
archive. Use `sase agent prompts list/show/validate` for archived prompts and their
published `ARTIFACTS` links. Use ACE's grouped `@` completion to browse prompt
references, or its contextual **Copy as…** palette to copy a reference or pre-fill a new
agent prompt from the selected entry. See
[Getting Started](getting_started.md#step-6-hand-off-existing-work-with-artifact-references)
for the handoff workflow and
[prompt preprocessing](llms.md#prompt-preprocessing-pipeline) for launch-time
resolution.

Operational commands are intentionally narrow. Helper bridges expose fixed JSON
operations for editor and mobile clients; they are not general shell or filesystem APIs.

### Doctor Support Reports

`sase doctor` is the first command to run when SASE behaves unexpectedly. It is
read-only by default: it does not launch agents, call LLM APIs, repair state, run tests,
or scan full artifact history. The human output is grouped by subsystem and puts
next-step commands beside warnings and errors.

Common forms:

```bash
sase doctor                 # compact human report
sase doctor -v              # include every check plus bounded details
sase doctor -j              # stable JSON report for scripts or support bundles
sase doctor -D              # add slower read-only deep checks
sase doctor -C runtime      # run one group
sase doctor -C llm.default  # run one check
sase doctor -C project.junk_directories -C workspace.missing_checkouts
```

Exit codes are designed for support-first use. `OK`, `WARN`, and all-skipped reports
exit `0`; `ERROR` exits `1`. Use `sase doctor -s` / `--strict` when automation should
treat warnings as failures.

The JSON report uses `schema_version: 1` and stable top-level fields such as `status`,
`counts`, `selected_checks`, and `checks`. Individual check `data` payloads stay bounded
and may gain additional keys over time, so scripts should key off check ids and statuses
rather than assuming every nested field is permanent.

`project.junk_directories` reports directories under `~/.sase/projects/` that have no
canonical ProjectSpec and gives a manual-review cleanup hint.
`workspace.missing_checkouts` scans enabled and disabled projects through the shared
inventory, lists registered checkout paths missing from disk, and suggests a per-project
`sase workspace repair -n` preview. Neither check mutates state.

When asking for help, attach `sase doctor -v` for a readable report or `sase doctor -j`
for a machine-readable report.
