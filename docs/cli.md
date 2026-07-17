# CLI Reference

This page is a command index for the top-level `sase` CLI. It is meant for discovery and routing: use it to find the
surface that owns a workflow, then follow the links to the detailed command, flag, or subsystem reference.

For exhaustive flag tables, see the [configuration reference](configuration.md#cli-flags).

## Daily Operation

| Command                         | Purpose                                                                                                              | Details                                               |
| ------------------------------- | -------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------- |
| `sase ace`                      | Open ACE, the interactive control surface for ChangeSpecs, live agents, notifications, and axe state.                | [ACE TUI](ace.md)                                     |
| `sase run [PROMPT]`             | Launch an agent or workflow from a prompt, an xprompt reference, a workflow reference, history, or an editor buffer. | [XPrompts](xprompt.md), [workflows](workflow_spec.md) |
| `sase agent list`               | List active and recent agents across projects.                                                                       | [ACE Agents tab](ace.md#tab-system)                   |
| `sase agent show`               | Render one agent's detail panel by name.                                                                             | [Agent attachments](agent_images.md)                  |
| `sase agent kill`               | Terminate a running agent.                                                                                           | [ACE TUI](ace.md)                                     |
| `sase agent tag`                | Set, clear, or list user-defined agent tags used for grouping.                                                       | [ACE TUI](ace.md)                                     |
| `sase agent archive`            | Maintain dismissed-agent bundle summary indexes (`rebuild-index`, `verify`).                                         | [ACE TUI](ace.md#agent-revival)                       |
| `sase agent artifacts`          | Inspect and migrate physical agent artifact storage layout.                                                          | [Configuration](configuration.md#directory-sharding)  |
| `sase agent index`              | Manage the persistent agent artifact SQLite index (`status`, `rebuild`, `verify`, `gc`).                             | [ACE TUI](ace.md)                                     |
| `sase agent names migrate-auto` | Backfill the permanent agent-name registry from legacy auto-generated names; pass `--force` to rerun.                | [ACE TUI](ace.md)                                     |
| `sase chat list`                | List recent chat transcripts.                                                                                        | [XPrompts](xprompt.md)                                |
| `sase chat show`                | Show one chat transcript by agent name, path, or basename.                                                           | [XPrompts](xprompt.md)                                |
| `sase prompt list`              | List, search, and filter previously submitted prompts (pretty table or JSON).                                        | [Prompt history](prompt.md)                           |
| `sase prompt show`              | Print one prompt's exact text as raw, Markdown, or JSON.                                                             | [Prompt history](prompt.md)                           |
| `sase prompt run`               | Replay a stored prompt by selector, optionally editing or re-prefixing it first.                                     | [Prompt history](prompt.md)                           |
| `sase prompt save`              | Save a stored prompt as a reusable xprompt, or `export` it to a file or SDD snapshot.                                | [Prompt history](prompt.md), [XPrompts](xprompt.md)   |
| `sase prompt prune`             | Curate the prompt-history store with `delete`, `prune`, and read-only `doctor`/`stats`.                              | [Prompt history](prompt.md)                           |
| `sase vcs list`                 | List the primary, linked, and SDD repositories with branch, dirty, commit-count, and activity summaries.             | [VCS](vcs.md#sase-vcs-list)                           |
| `sase vcs log`                  | Show a primary/linked timeline; `--sdd` opts into separate SDD history in current or all-project scope.              | [VCS](vcs.md#sase-vcs-log)                            |
| `sase notify`                   | Shortcut for `sase notify list`.                                                                                     | [Notifications](notifications.md)                     |
| `sase notify create`            | Create a raw notification or durable command-backed gate from JSON input.                                            | [Notifications](notifications.md)                     |
| `sase notify list`              | List recent notifications, optionally filtered by sender, tag, unread state, or query.                               | [Notifications](notifications.md)                     |
| `sase notify show`              | Show one notification as Markdown or JSON.                                                                           | [Notifications](notifications.md)                     |
| `sase notify wait`              | Wait mechanically for a command-backed gate and return its terminal result.                                          | [Notifications](notifications.md)                     |
| `sase repro replay`             | Replay an Agents-tab reproduction bundle through the headless TUI harness and emit a verdict.                        | [ACE TUI](ace.md#agents-tab-reproduction-bundles)     |
| `sase repro capture agents-tab` | Capture a commit-safe out-of-band Agents-tab bundle from current filesystem state.                                   | [ACE TUI](ace.md#agents-tab-reproduction-bundles)     |

`sase run` launches detached background agents that appear in the ACE Agents tab. It can start from prompt text, xprompt
or workflow references, the editor, or the prompt-history picker, and multi-prompt input expands into sequential
background launches. ACE uses the same launch machinery when users start agents from the TUI.

Command groups with an exact `list` child default to that list view when invoked bare, including `sase bead`,
`sase chat`, `sase file`, `sase file-history`, `sase memory`, `sase notify`, `sase plugin`, `sase project`,
`sase prompt`, `sase skill`, `sase telemetry`, `sase workspace`, and `sase xprompt`. Nested groups such as
`sase agent tag`, `sase axe chop`, `sase axe lumberjack`, `sase memory agent-docs`, and `sase plan links` follow the
same rule.

The bare form is only the default view. When you need flags that belong to the list command, keep the `list` subcommand
explicit, for example `sase notify list -j`, `sase memory list -j`, or `sase workspace list --json`.

## Work Tracking And Planning

| Command                                      | Purpose                                                                                                     | Details                                                             |
| -------------------------------------------- | ----------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------- |
| `sase changespec current`                    | Render the ChangeSpec associated with the current workspace.                                                | [ChangeSpecs](change_spec.md)                                       |
| `sase changespec migrate-extension`          | Rename legacy `.gp` ProjectSpec files to the canonical `.sase` extension.                                   | [ProjectSpec](project_spec.md)                                      |
| `sase changespec search`                     | Search and filter ChangeSpecs with the query language.                                                      | [Query language](query_language.md)                                 |
| `sase changespec sync-deltas`                | Recompute the `DELTAS` field for a ChangeSpec from VCS state.                                               | [ChangeSpecs](change_spec.md)                                       |
| `sase init`                                  | Check and initialize memory, repositories, and skills for the current project.                              | [Initialization](init.md)                                           |
| `sase init --all --check`                    | Check every enabled main project without writing; report one aggregate status.                              | [Initialization](init.md)                                           |
| `sase init --all --yes`                      | Initialize every enabled main project without generic prompts; sidecar creation still asks.                 | [Initialization](init.md)                                           |
| `sase memory` / `sase memory list`           | Show loaded, referenced, available, and missing memory files.                                               | [Memory](memory.md#inspect-context)                                 |
| `sase memory agent-docs list`                | Inventory project, home, and chezmoi `AGENTS.md` files plus nearby provider shims.                          | [Initialization](init.md#agent-documents)                           |
| `sase memory read`                           | Agent-side read of one long-term memory file with an attributable audit event.                              | [Memory](memory.md#audited-reads)                                   |
| `sase memory write`                          | Agent-side proposal for human-reviewed long-term memory; `--notify` can add an inbox item.                  | [Memory](memory.md#propose-memory)                                  |
| `sase memory review`                         | Human listing, inspection, approval, editing, or rejection of pending memory proposals.                     | [Memory](memory.md#review-proposals)                                |
| `sase memory log`                            | Summarize audited memory reads; `--include proposals` also shows proposal and review events.                | [Memory](memory.md#audited-reads)                                   |
| `sase memory init`                           | Refresh home and SASE-managed project memory; copy existing AGENTS.md files to provider instructions.       | [Initialization](init.md#memory-initialization)                     |
| `sase init memory`                           | Alias for `sase memory init`.                                                                               | [Initialization](init.md#memory-initialization)                     |
| `sase repo init`                             | Initialize configured sidecars, generated guides, config, and repository ignores.                           | [Initialization](init.md)                                           |
| `sase init repo`                             | Alias for `sase repo init`.                                                                                 | [Initialization](init.md)                                           |
| `sase repo path REPO`                        | Print a primary or sidecar path; `--ensure` materializes the selected sidecar.                              | [SDD Storage](sdd_storage.md)                                       |
| `sase plan links [list]`                     | Inspect prompt/plan frontmatter links; bare `links` defaults to `list`.                                     | [SDD](sdd.md)                                                       |
| `sase plan links repair`                     | Infer and optionally write missing bidirectional SDD links.                                                 | [SDD](sdd.md)                                                       |
| `sase plan links validate`                   | Validate SDD frontmatter links.                                                                             | [SDD](sdd.md)                                                       |
| `sase plan search`                           | Search or browse tale, epic, prompt, and research artifacts.                                                | [SDD](sdd.md)                                                       |
| `sase plan validate PLAN_FILE -t TIER`       | Strictly validate one plan against the tale or epic frontmatter schema.                                     | [SDD](sdd.md#plan-frontmatter-schema-and-validation)                |
| `sase bead onboard`                          | Print the bead quick-start guide.                                                                           | [Beads](beads.md)                                                   |
| `sase bead init`                             | Initialize bead storage for the current project.                                                            | [Beads](beads.md#storage)                                           |
| `sase bead create`                           | Create plan, epic, or phase issues.                                                                         | [Beads](beads.md#cli-commands)                                      |
| `sase bead list`                             | List bead issues by status, type, or tier.                                                                  | [Beads](beads.md#cli-commands)                                      |
| `sase bead search`                           | Search bead IDs, titles, notes, plan paths, metadata, and lifecycle fields.                                 | [Beads](beads.md#sase-bead-search-query)                            |
| `sase bead ready`                            | Show open issues whose dependencies are closed.                                                             | [Beads](beads.md#dependencies)                                      |
| `sase bead blocked`                          | Show issues blocked by open dependencies.                                                                   | [Beads](beads.md#dependencies)                                      |
| `sase bead show`                             | Show one issue.                                                                                             | [Beads](beads.md#cli-commands)                                      |
| `sase bead update` / `open` / `close` / `rm` | Mutate issue metadata or lifecycle state.                                                                   | [Beads](beads.md#cli-commands)                                      |
| `sase bead dep add`                          | Add an issue dependency.                                                                                    | [Beads](beads.md#dependencies)                                      |
| `sase bead sync`                             | Export the bead database to git-tracked JSONL and stage it.                                                 | [Beads](beads.md#sync-mechanism)                                    |
| `sase bead stats` / `doctor`                 | Inspect project statistics or bead-store health.                                                            | [Beads](beads.md#rust-backend)                                      |
| `sase bead work`                             | Launch phase agents for an epic.                                                                            | [Beads](beads.md#sase-bead-work-target)                             |
| `sase project list`                          | List enabled projects by default, or inspect disabled/internal backing records with `--state`.              | [Project lifecycle](project_spec.md#project-lifecycle)              |
| `sase project show`                          | Show lifecycle, workspace, launchability, and warning details for one project.                              | [Project lifecycle](project_spec.md#project-lifecycle)              |
| `sase project enable` / `disable`            | Apply the normal user-facing `PROJECT_STATE` transitions under lock.                                        | [Project lifecycle](project_spec.md#project-lifecycle)              |
| `sase project set-state`                     | Set a lifecycle or internal backing state under the ProjectSpec lock.                                       | [Project lifecycle](project_spec.md#project-lifecycle)              |
| `sase project alias`                         | List, add, remove, or clear `PROJECT_ALIASES` under the ProjectSpec lock.                                   | [Project names](project_spec.md#project-names-and-aliases)          |
| `sase plan` / `sase plan list`               | Show pending proposals, recent approvals, and inferred rejected archived proposals.                         | [XPrompt directives](xprompt.md#plan-directive)                     |
| `sase plan approve`                          | Approve one pending plan by ID or prefix; `--kind` chooses approve/commit/epic/tale.                        | [Plan approval pipeline](agent_families.md)                         |
| `sase plan propose`                          | Submit a plan file for approval from the plan skill path.                                                   | [XPrompt directives](xprompt.md#plan-directive)                     |
| `sase plan reject`                           | Reject one pending plan by ID or prefix, then attempt planner cleanup when found.                           | [XPrompt directives](xprompt.md#plan-directive)                     |
| `sase plan search`                           | Search resolved-store SDD plans and the machine-local plan archive by literal text and metadata.            | [SDD](sdd.md#how-sdd-works)                                         |
| `sase plan validate`                         | Validate one explicit plan path against a required `tale` or `epic` schema, with human or JSON diagnostics. | [SDD](sdd.md#plan-frontmatter-schema-and-validation)                |
| `sase launch request`                        | Register a launch gate; agent callers wait for a deterministic terminal JSON outcome.                       | [Agent Families](agent_families.md#agent-initiated-family-launches) |
| `sase launch approve` / `reject`             | Resolve a pending launch request by request id, notification id, or unique prefix.                          | [Agent Families](agent_families.md#agent-initiated-family-launches) |
| `sase questions`                             | Ask structured user questions from the questions skill path.                                                | [XPrompt directives](xprompt.md#directives)                         |

ChangeSpecs are PR-sized review records. SDD stores durable prompt and planning artifacts. Beads add git-portable
dependency tracking and executable epics on top of those artifacts.

`sase project` defaults to `sase project list`, and `sase project list` defaults to enabled true projects. Use
`sase project list --state all --json` to inspect disabled projects and internal `sibling` backing records,
`sase project disable <project>` to hide a dormant project from default launch views, and
`sase project enable <project>` to make it launchable again. Disabling refuses projects with live `RUNNING` claims or
active artifact markers unless `--force` is passed. Legacy active/inactive values and the deprecated lifecycle command
aliases remain read-compatible. ACE's **Projects** tab (in the SASE Admin Center, opened with `#`) provides the
interactive counterpart, including marking multiple projects, editing a ProjectSpec in `$EDITOR`, and deleting obsolete
SASE project directories after confirmation. There is no CLI delete subcommand; full project-directory deletion is only
available from ACE's Projects tab and removes state under `~/.sase/projects/`, not workspace checkouts.

`sase project alias list [PROJECT] [-j|--json]`, `add PROJECT ALIAS`, `remove PROJECT ALIAS`, and `clear PROJECT` manage
ProjectSpec aliases. The ACE Projects sub-tab (in the SASE Admin Center, opened with `#`) also displays aliases,
includes them in filtering, and opens an alias editor with `A`. Alias refs are accepted in launch-bound VCS workspace
tags, but prompt history, agent metadata, and artifacts use the canonical directory-key project name. ProjectSpecs may
also carry `PROJECT_NAME` as the primary user-facing name. For example, the GitHub provider can create
`PROJECT_NAME: foo` and then `PROJECT_NAME: foo_1` for distinct `owner/foo` repositories while keeping stable canonical
project records. Existing auto-aliased GitHub projects remain valid and keep resolving through `PROJECT_ALIASES`.

Enabled-only true-project discovery is also the default for launch pickers, ChangeSpec searches, project-local xprompt
catalogs, broad mobile helper catalogs, and all-known bead helper reads. Internal sibling backing records are hidden
from those surfaces and support configured linked repositories. Agents prepare one through `/sase_repo`; the underlying
audited open infers the host project and workspace from cwd. Agent-history views that need older artifacts opt into all
project states explicitly. An explicitly typed known-project VCS ref is a launch-time exception: it re-enables a
disabled project before claiming a workspace. A checkout cwd or mobile `project` value is only prompt-resolution
context, not a workspace ref; without an explicit ref, a bare prompt defaults to `#git:home`. Direct low-level claims
against a disabled ProjectSpec remain blocked until the project is enabled.

`sase plan` defaults to `sase plan list`. The dashboard has Proposed, Approved, and Rejected sections; use repeatable
`-s/--status` options to select sections, `-n/--limit` to set each history section's size (`0` is unlimited), and
`-t/--tier` to filter by plan-file tier. Proposed rows are never limited and are the actionable rows; each includes an
`id_prefix`, agent, project, provider/model, plan path, and response directory. Pass that prefix to
`sase plan approve <prefix>` or `sase plan reject <prefix>`. If the selector is omitted, exactly one pending proposal
must exist. When `--kind` is omitted, approval follows the plan's authored `tier`; an explicit kind overrides it. The
Rejected section is inferred from archived proposal files that are not represented by the proposed or approved state; it
is a history aid, not the selector source for new actions. The approval kind is the workflow choice: `approve` runs the
coder without asking the runner to commit an SDD plan, `tale` commits the plan as an SDD tale and then runs the coder,
`epic` commits the matching SDD tier and launches the bead follow-up, and `commit` records the approved plan in SDD
without launching a coder. Use `-m/--model` to pick the follow-up agent's model. Use `-p/--prompt` to add extra coder
instructions for the `approve` and `tale` paths. Tale and epic approvals validate against their target schema before
writing a response; a failure prints the diagnostics and expected schema and leaves the proposal pending for retry.
`sase plan reject` writes the rejection response first, then uses the same durable cleanup path as the TUI no-feedback
rejection action when the matching planner row is still discoverable. If cleanup cannot find or kill the row, the CLI
reports that separately after the plan has already been rejected.

`sase plan search [QUERY]` searches plans in the resolved SDD store (the `repo` source) and the machine-local
`~/.sase/plans/` archive. Omit the query to browse with metadata filters. Compact and Markdown output group SDD-store
matches above local matches; JSON and full output keep ranked result order with SDD-store matches prioritized over
otherwise-similar local matches. Useful filters include `--kind`, `--status`, `--source`, `--since`, `--until`,
`--sort`, and `--format json|markdown` for agent-friendly output.

`sase plan validate PLAN_FILE -t tale|epic` validates exactly one path without requiring a project or agent context. It
reports every schema problem in one run and prints the expected tier schema plus a minimal valid example on failure. Use
`-j/--json` for the stable machine-readable envelope or `-q/--quiet` to suppress successful human output. A valid plan
exits 0, a validation failure exits 1, and invalid command usage exits 2.

## Automation

| Command                          | Purpose                                                  | Details                                            |
| -------------------------------- | -------------------------------------------------------- | -------------------------------------------------- |
| `sase axe start`                 | Start the axe orchestrator and its lumberjacks.          | [Axe](axe.md)                                      |
| `sase axe stop`                  | Stop the running orchestrator.                           | [Axe](axe.md#cli-commands)                         |
| `sase axe chop list`             | List configured chops with status; `-a` adds scripts.    | [Axe chops](axe.md#chop-fields)                    |
| `sase axe chop doctor`           | Diagnose configured/available chops and Telegram setup.  | [Axe chops](axe.md#chop-fields)                    |
| `sase axe chop run <name>`       | Run one chop in the foreground.                          | [Axe chops](axe.md#script-chops)                   |
| `sase axe lumberjack list`       | List configured lumberjacks.                             | [Axe lumberjacks](axe.md#default-lumberjacks)      |
| `sase axe lumberjack run <name>` | Run one lumberjack in the foreground for debugging.      | [Axe lumberjacks](axe.md#lumberjack-configuration) |
| `sase axe lumberjack status`     | Show lumberjack process status.                          | [Axe](axe.md)                                      |
| `sase axe maintenance enter`     | Pause scheduled lumberjack ticks with a recorded reason. | [Maintenance mode](axe.md#maintenance-mode)        |
| `sase axe maintenance exit`      | Resume scheduled lumberjack ticks.                       | [Maintenance mode](axe.md#maintenance-mode)        |
| `sase axe maintenance status`    | Inspect the maintenance marker.                          | [Maintenance mode](axe.md#maintenance-mode)        |

Axe runs scheduled hooks, mentors, comment polling, workflow checks, `%wait` dependency resolution, cleanup, and error
digests. ACE starts axe automatically unless launched with `sase ace --no-axe`.

## Prompt And Workflow Authoring

| Command                          | Purpose                                                                     | Details                                                                                     |
| -------------------------------- | --------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------- |
| `sase xprompt expand`            | Expand xprompt references in prompt text, with optional trace output.       | [XPrompt reference syntax](xprompt.md#reference-syntax)                                     |
| `sase xprompt explain`           | Dry-run a workflow and show the execution plan.                             | [Workflows](workflow_spec.md)                                                               |
| `sase xprompt list`              | Emit the structured xprompt catalog as JSON.                                | [XPrompt catalog](xprompt.md#cli-subcommands)                                               |
| `sase xprompt graph`             | Generate a workflow DAG as Mermaid or text.                                 | [Workflow graphing](xprompt.md#cli-subcommands)                                             |
| `sase xprompt catalog`           | Render visible xprompts to a formatted PDF catalog.                         | [XPrompt catalog](xprompt.md#cli-subcommands)                                               |
| `sase lsp`                       | Start the xprompt language server over stdio.                               | [Editor integration](editor.md#language-server)                                             |
| `sase editor helper-bridge`      | JSON helper operations for editor integrations.                             | [Editor helper bridge](editor.md#helper-bridge)                                             |
| `sase file list`                 | Emit JSON filesystem completion candidates.                                 | [Editor completion commands](configuration.md#sase-file)                                    |
| `sase file-history list`         | Emit recently referenced files for editor completion.                       | [Editor completion commands](configuration.md#sase-file-history)                            |
| `sase file-history delete`       | Remove one path from the file-reference history.                            | [Editor completion commands](configuration.md#sase-file-history)                            |
| `sase skill` / `sase skill list` | Inspect generated skill sources, provider targets, and deployed-file drift. | [Initialization](init.md#skill-initialization), [bundled skills](xprompt.md#bundled-skills) |
| `sase skill init`                | Generate and deploy agent skill files from xprompt source templates.        | [Initialization](init.md#skill-initialization), [bundled skills](xprompt.md#bundled-skills) |
| `sase skill log`                 | Summarize or inspect audited generated skill-use events.                    | [Skill field](xprompt.md#skill-field)                                                       |
| `sase skill use`                 | Agent-side audit event recording that a generated skill was used.           | [Skill field](xprompt.md#skill-field)                                                       |
| `sase init skills`               | Compatibility alias for `sase skill init`.                                  | [Initialization](init.md#skill-initialization)                                              |

Use `#name(...)` for inline xprompt expansion and `#!workflow(...)` for standalone workflow references. Workspace
references such as `#git:<project>` and plugin-provided references are resolved before the prompt or workflow runs.

## Review And Delivery

| Command         | Purpose                                                                 | Details                                 |
| --------------- | ----------------------------------------------------------------------- | --------------------------------------- |
| `sase commit`   | Dispatch a commit, proposal, or PR through the configured VCS provider. | [Commit workflows](commit_workflows.md) |
| `sase revert`   | Revert a ChangeSpec by pruning its change and archiving its diff.       | [Commit workflows](commit_workflows.md) |
| `sase restore`  | Restore a reverted ChangeSpec by reapplying its archived diff.          | [Commit workflows](commit_workflows.md) |
| `sase comments` | Preview mentor comments from JSON with syntax-highlighted code context. | [Mentors](mentors.md)                   |

Delivery commands delegate to the VCS and workspace provider layers, so the same command surface can support plain git,
GitHub pull requests, and other provider plugins.

## Operations And Diagnostics

| Command                        | Purpose                                                                                                                                                               | Details                                                                                                              |
| ------------------------------ | --------------------------------------------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------- |
| `sase doctor`                  | Run read-only install, config, provider, project, and state diagnostics for support.                                                                                  | [Doctor support reports](#doctor-support-reports)                                                                    |
| `sase config layers`           | Show the configuration merge chain.                                                                                                                                   | [Configuration](configuration.md)                                                                                    |
| `sase config show`             | Dump the final merged configuration, optionally filtered by key.                                                                                                      | [Configuration](configuration.md)                                                                                    |
| `sase config mentor-match`     | Trace mentor profile matching for a ChangeSpec.                                                                                                                       | [Mentors](mentors.md)                                                                                                |
| `sase core health`             | Check that the required `sase_core_rs` extension is loadable and working.                                                                                             | [Rust backend](rust_backend.md)                                                                                      |
| `sase validate`                | Run SASE validation checks: initialization drift plus SDD frontmatter validation.                                                                                     | [Initialization](init.md), [SDD](sdd.md)                                                                             |
| `sase telemetry status`        | Show telemetry configuration and reachability.                                                                                                                        | [Telemetry](telemetry.md)                                                                                            |
| `sase telemetry list`          | Display the metric catalog.                                                                                                                                           | [Telemetry](telemetry.md)                                                                                            |
| `sase telemetry snapshot`      | Fetch current metric values.                                                                                                                                          | [Telemetry](telemetry.md)                                                                                            |
| `sase telemetry dashboard`     | Open the live telemetry dashboard.                                                                                                                                    | [Telemetry](telemetry.md)                                                                                            |
| `sase telemetry health`        | Run subsystem health assessment.                                                                                                                                      | [Telemetry](telemetry.md)                                                                                            |
| `sase telemetry export-config` | Export the bundled monitoring stack.                                                                                                                                  | [Telemetry](telemetry.md)                                                                                            |
| `sase version`                 | Show the local `sase`, `sase-core-rs`, and installed plugin package inventory for this runtime.                                                                       | [Runtime inventory](configuration.md#sase-version)                                                                   |
| `sase plugin` / `plugin list`  | Browse the plugin catalog, marking built-in, community, installed, latest, and `↑` update indicators.                                                                 | [Plugin catalog](plugins.md#plugin-catalog-sase-plugin-list-sase-plugin-show)                                        |
| `sase plugin show`             | Show one plugin's detail panel: install status, latest version, repository, topics, and metadata.                                                                     | [Plugin catalog](plugins.md#plugin-catalog-sase-plugin-list-sase-plugin-show)                                        |
| `sase plugin install`          | Install a plugin into sase's own uv tool environment, resolving the name through the catalog.                                                                         | [Installing and updating plugins](plugins.md#installing-and-updating-plugins-sase-plugin-install-sase-plugin-update) |
| `sase plugin update`           | Upgrade one installed plugin (or every plugin with `-a`), leaving sase core pinned.                                                                                   | [Installing and updating plugins](plugins.md#installing-and-updating-plugins-sase-plugin-install-sase-plugin-update) |
| `sase plugin uninstall`        | Remove one installed plugin from sase's own uv tool environment, preserving core and other plugins.                                                                   | [Removing a plugin](plugins.md#removing-a-plugin-sase-plugin-uninstall)                                              |
| `sase update`                  | Upgrade sase and all installed plugins together; registry packages via `uv tool upgrade`, editable/dev installs via git fast-forward. `-n` previews, `-j` emits JSON. | [Updating sase and plugins](plugins.md#updating-sase-and-plugins-sase-update)                                        |
| `sase logs`                    | Collect and package agent run logs for a date range.                                                                                                                  | [Configuration CLI flags](configuration.md#sase-logs)                                                                |
| `sase revive-log`              | Inspect the agent-revival audit log (start / success / failure events).                                                                                               | [Agent revival audit log](troubleshooting/agent-revival.md)                                                          |
| `sase artifact create`         | Move an explicit file into persistent agent artifact storage.                                                                                                         | [Agent attachments](agent_images.md)                                                                                 |
| `sase var set`                 | Attach named output variables for ACE metadata and waited-agent Jinja rendering.                                                                                      | [XPrompt variables](xprompt.md#cross-agent-output-variables)                                                         |
| `sase path`                    | Print well-known paths such as schemas and xprompt directories.                                                                                                       | [Configuration CLI flags](configuration.md#sase-path)                                                                |
| `sase repo list`               | Show primary, sidecar, linked, and opened external repos; use `--all` or `--json` for cross-project and clone-matrix views.                                           | [Configuration CLI flags](configuration.md#sase-repo)                                                                |
| `sase repo log`                | Summarize the durable repository-open audit log, with repo, agent, workspace, event-ID, and JSON filters.                                                             | [Configuration CLI flags](configuration.md#sase-repo)                                                                |
| `sase repo open`               | Open an inventory repo, another SASE project, or `gh:owner/repo` external in the inferred workspace, then print its path.                                             | [Configuration CLI flags](configuration.md#sase-repo)                                                                |
| `sase workspace list`          | List one project's registry or use `--all` for the cross-project workspace inventory.                                                                                 | [Workspace provider](workspace.md)                                                                                   |
| `sase workspace path`          | Print the checkout path for a workspace number.                                                                                                                       | [Workspace provider](workspace.md)                                                                                   |
| `sase workspace cleanup`       | Remove stale unclaimed managed checkouts older than the configured TTL.                                                                                               | [Workspace provider](workspace.md)                                                                                   |
| `sase workspace repair`        | Reconcile the workspace registry with the filesystem.                                                                                                                 | [Workspace provider](workspace.md)                                                                                   |
| `sase workspace migrate`       | Opt-in move of adjacent checkouts to a managed root, with optional symlink transition and finalization.                                                               | [Workspace provider](workspace.md)                                                                                   |
| `sase mobile gateway start`    | Start the workstation-hosted mobile gateway.                                                                                                                          | [Mobile gateway](mobile_gateway.md)                                                                                  |
| `sase mobile agent-bridge`     | Fixed JSON bridge used by the mobile gateway for agent operations.                                                                                                    | [Mobile gateway](mobile_gateway.md)                                                                                  |
| `sase mobile helper-bridge`    | Fixed JSON bridge used by the mobile gateway for workflow helper operations.                                                                                          | [Mobile gateway](mobile_gateway.md)                                                                                  |

Operational commands are intentionally narrow. Helper bridges expose fixed JSON operations for editor and mobile
clients; they are not general shell or filesystem APIs.

### Doctor Support Reports

`sase doctor` is the first command to run when SASE behaves unexpectedly. It is read-only by default: it does not launch
agents, call LLM APIs, repair state, run tests, or scan full artifact history. The human output is grouped by subsystem
and puts next-step commands beside warnings and errors.

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

Exit codes are designed for support-first use. `OK`, `WARN`, and all-skipped reports exit `0`; `ERROR` exits `1`. Use
`sase doctor -s` / `--strict` when automation should treat warnings as failures.

The JSON report uses `schema_version: 1` and stable top-level fields such as `status`, `counts`, `selected_checks`, and
`checks`. Individual check `data` payloads stay bounded and may gain additional keys over time, so scripts should key
off check ids and statuses rather than assuming every nested field is permanent.

`project.junk_directories` reports directories under `~/.sase/projects/` that have no canonical ProjectSpec and gives a
manual-review cleanup hint. `workspace.missing_checkouts` scans enabled and disabled projects through the shared
inventory, lists registered checkout paths missing from disk, and suggests a per-project `sase workspace repair -n`
preview. Neither check mutates state.

When asking for help, attach `sase doctor -v` for a readable report or `sase doctor -j` for a machine-readable report.
