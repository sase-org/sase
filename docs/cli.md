# CLI Reference

This page is a command index for the top-level `sase` CLI. It is meant for discovery and routing: use it to find the
surface that owns a workflow, then follow the links to the detailed command, flag, or subsystem reference.

For exhaustive flag tables, see the [configuration reference](configuration.md#cli-flags).

## Daily Operation

| Command                              | Purpose                                                                                                              | Details                                               |
| ------------------------------------ | -------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------- |
| `sase ace`                           | Open ACE, the interactive control surface for ChangeSpecs, live agents, notifications, and axe state.                | [ACE TUI](ace.md)                                     |
| `sase run [PROMPT]`                  | Launch an agent or workflow from a prompt, an xprompt reference, a workflow reference, history, or an editor buffer. | [XPrompts](xprompt.md), [workflows](workflow_spec.md) |
| `sase agents status`                 | List active and recent agents across projects.                                                                       | [ACE Agents tab](ace.md#tab-system)                   |
| `sase agents show`                   | Render one agent's detail panel by name, timestamp, or path.                                                         | [Agent attachments](agent_images.md)                  |
| `sase agents kill`                   | Terminate a running agent.                                                                                           | [ACE TUI](ace.md)                                     |
| `sase agents tag`                    | Set, clear, or list user-defined agent tags used for grouping.                                                       | [ACE TUI](ace.md)                                     |
| `sase agents archive`                | Maintain dismissed-agent bundle summary indexes (`rebuild-index`, `verify`).                                         | [ACE TUI](ace.md#agent-revival)                       |
| `sase agents index`                  | Manage the persistent agent artifact SQLite index (`status`, `rebuild`, `verify`, `gc`).                             | [ACE TUI](ace.md)                                     |
| `sase agents names migrate-auto`     | Backfill the permanent agent-name registry from legacy auto-generated names; pass `--force` to rerun.                | [ACE TUI](ace.md)                                     |
| `sase chats list`                    | List recent chat transcripts.                                                                                        | [XPrompts](xprompt.md)                                |
| `sase chats show`                    | Show one chat transcript by agent name, path, or basename.                                                           | [XPrompts](xprompt.md)                                |
| `sase notify` / `sase notify create` | Create a notification from JSON input.                                                                               | [Notifications](notifications.md)                     |
| `sase notify list`                   | List recent notifications, optionally filtered by sender, unread state, or query.                                    | [Notifications](notifications.md)                     |
| `sase notify show`                   | Show one notification as Markdown or JSON.                                                                           | [Notifications](notifications.md)                     |
| `sase repro replay`                  | Replay an Agents-tab reproduction bundle through the headless TUI harness and emit a verdict.                        | [ACE TUI](ace.md#agents-tab-reproduction-bundles)     |
| `sase repro capture agents-tab`      | Capture a commit-safe out-of-band Agents-tab bundle from current filesystem state.                                   | [ACE TUI](ace.md#agents-tab-reproduction-bundles)     |

`sase run` can run in the foreground, launch detached background agents with `--daemon`, resume previous conversations,
or expand multi-prompt input into sequential background launches. ACE uses the same launch machinery when users start
agents from the TUI.

## Work Tracking And Planning

| Command                                      | Purpose                                                                   | Details                                         |
| -------------------------------------------- | ------------------------------------------------------------------------- | ----------------------------------------------- |
| `sase changespec current`                    | Render the ChangeSpec associated with the current workspace.              | [ChangeSpecs](change_spec.md)                   |
| `sase changespec migrate-extension`          | Rename legacy `.gp` ProjectSpec files to the canonical `.sase` extension. | [ProjectSpec](project_spec.md)                  |
| `sase changespec search`                     | Search and filter ChangeSpecs with the query language.                    | [Query language](query_language.md)             |
| `sase changespec sync-deltas`                | Recompute the `DELTAS` field for a ChangeSpec from VCS state.             | [ChangeSpecs](change_spec.md)                   |
| `sase sdd init`                              | Create or refresh SDD README files and directory map assets.              | [SDD](sdd.md)                                   |
| `sase sdd list`                              | List SDD prompt, tale, epic, legend, or all Markdown artifacts.           | [SDD](sdd.md)                                   |
| `sase sdd links`                             | Inspect prompt/artifact frontmatter links.                                | [SDD](sdd.md)                                   |
| `sase sdd validate`                          | Validate SDD frontmatter links.                                           | [SDD](sdd.md)                                   |
| `sase sdd repair-links`                      | Infer and optionally write missing bidirectional SDD links.               | [SDD](sdd.md)                                   |
| `sase bead onboard`                          | Print the bead quick-start guide.                                         | [Beads](beads.md)                               |
| `sase bead init`                             | Initialize bead storage for the current project.                          | [Beads](beads.md#storage)                       |
| `sase bead create`                           | Create plan, epic, legend, or phase issues.                               | [Beads](beads.md#cli-commands)                  |
| `sase bead list`                             | List bead issues by status, type, or tier.                                | [Beads](beads.md#cli-commands)                  |
| `sase bead ready`                            | Show open issues whose dependencies are closed.                           | [Beads](beads.md#dependencies)                  |
| `sase bead blocked`                          | Show issues blocked by open dependencies.                                 | [Beads](beads.md#dependencies)                  |
| `sase bead show`                             | Show one issue.                                                           | [Beads](beads.md#cli-commands)                  |
| `sase bead update` / `open` / `close` / `rm` | Mutate issue metadata or lifecycle state.                                 | [Beads](beads.md#cli-commands)                  |
| `sase bead dep add`                          | Add an issue dependency.                                                  | [Beads](beads.md#dependencies)                  |
| `sase bead sync`                             | Export the bead database to git-tracked JSONL and stage it.               | [Beads](beads.md#sync-mechanism)                |
| `sase bead stats` / `doctor`                 | Inspect project statistics or bead-store health.                          | [Beads](beads.md#rust-backend)                  |
| `sase bead work`                             | Launch phase agents for an epic, or epic-planning agents for a legend.    | [Beads](beads.md#sase-bead-work-id)             |
| `sase plan`                                  | Submit a plan for approval from the plan skill path.                      | [XPrompt directives](xprompt.md#plan-directive) |
| `sase questions`                             | Ask structured user questions from the questions skill path.              | [XPrompt directives](xprompt.md#directives)     |

ChangeSpecs are CL/PR-sized review records. SDD stores durable prompt and planning artifacts. Beads add git-portable
dependency tracking and executable epics on top of those artifacts.

## Automation

| Command                          | Purpose                                                  | Details                                            |
| -------------------------------- | -------------------------------------------------------- | -------------------------------------------------- |
| `sase axe start`                 | Start the axe orchestrator and its lumberjacks.          | [Axe](axe.md)                                      |
| `sase axe stop`                  | Stop the running orchestrator.                           | [Axe](axe.md#cli-commands)                         |
| `sase axe chop list`             | List configured chop jobs.                               | [Axe chops](axe.md#chop-fields)                    |
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

| Command                     | Purpose                                                               | Details                                                          |
| --------------------------- | --------------------------------------------------------------------- | ---------------------------------------------------------------- |
| `sase xprompt expand`       | Expand xprompt references in prompt text, with optional trace output. | [XPrompt reference syntax](xprompt.md#reference-syntax)          |
| `sase xprompt explain`      | Dry-run a workflow and show the execution plan.                       | [Workflows](workflow_spec.md)                                    |
| `sase xprompt list`         | Emit the structured xprompt catalog as JSON.                          | [XPrompt catalog](xprompt.md#cli-subcommands)                    |
| `sase xprompt graph`        | Generate a workflow DAG as Mermaid or text.                           | [Workflow graphing](xprompt.md#cli-subcommands)                  |
| `sase xprompt catalog`      | Render visible xprompts to a formatted PDF catalog.                   | [XPrompt catalog](xprompt.md#cli-subcommands)                    |
| `sase lsp`                  | Start the xprompt language server over stdio.                         | [Editor integration](editor.md#language-server)                  |
| `sase editor helper-bridge` | JSON helper operations for editor integrations.                       | [Editor helper bridge](editor.md#helper-bridge)                  |
| `sase file list`            | Emit JSON filesystem completion candidates.                           | [Editor completion commands](configuration.md#sase-file)         |
| `sase file-history list`    | Emit recently referenced files for editor completion.                 | [Editor completion commands](configuration.md#sase-file-history) |
| `sase file-history delete`  | Remove one path from the file-reference history.                      | [Editor completion commands](configuration.md#sase-file-history) |
| `sase init skills`          | Generate and deploy agent skill files from xprompt source templates.  | [Bundled skills](xprompt.md#bundled-skills)                      |

Use `#name(...)` for inline xprompt expansion and `#!workflow(...)` for standalone workflow references. Workspace
references such as `#cd:<path>`, `#git:<project>`, and plugin-provided references are resolved before the prompt or
workflow runs.

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

| Command                        | Purpose                                                                                                 | Details                                                     |
| ------------------------------ | ------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------- |
| `sase config layers`           | Show the configuration merge chain.                                                                     | [Configuration](configuration.md)                           |
| `sase config show`             | Dump the final merged configuration, optionally filtered by key.                                        | [Configuration](configuration.md)                           |
| `sase config mentor-match`     | Trace mentor profile matching for a ChangeSpec.                                                         | [Mentors](mentors.md)                                       |
| `sase core health`             | Check that the required `sase_core_rs` extension is loadable and working.                               | [Rust backend](rust_backend.md)                             |
| `sase telemetry status`        | Show telemetry configuration and reachability.                                                          | [Telemetry](telemetry.md)                                   |
| `sase telemetry list`          | Display the metric catalog.                                                                             | [Telemetry](telemetry.md)                                   |
| `sase telemetry snapshot`      | Fetch current metric values.                                                                            | [Telemetry](telemetry.md)                                   |
| `sase telemetry dashboard`     | Open the live telemetry dashboard.                                                                      | [Telemetry](telemetry.md)                                   |
| `sase telemetry health`        | Run subsystem health assessment.                                                                        | [Telemetry](telemetry.md)                                   |
| `sase telemetry export-config` | Export the bundled monitoring stack.                                                                    | [Telemetry](telemetry.md)                                   |
| `sase logs`                    | Collect and package agent run logs for a date range.                                                    | [Configuration CLI flags](configuration.md#sase-logs)       |
| `sase revive-log`              | Inspect the agent-revival audit log (start / success / failure events).                                 | [Agent revival audit log](troubleshooting/agent-revival.md) |
| `sase artifact create`         | Move an explicit file into persistent agent artifact storage.                                           | [Agent attachments](agent_images.md)                        |
| `sase path`                    | Print well-known paths such as schemas and xprompt directories.                                         | [Configuration CLI flags](configuration.md#sase-path)       |
| `sase workspace list`          | List managed workspace checkouts in the registry, including primary `#0`.                               | [Workspace provider](workspace.md)                          |
| `sase workspace path`          | Print the checkout path for a workspace number.                                                         | [Workspace provider](workspace.md)                          |
| `sase workspace open`          | Print (currently) the checkout path for a workspace number.                                             | [Workspace provider](workspace.md)                          |
| `sase workspace cleanup`       | Remove stale unclaimed managed checkouts older than the configured TTL.                                 | [Workspace provider](workspace.md)                          |
| `sase workspace repair`        | Reconcile the workspace registry with the filesystem.                                                   | [Workspace provider](workspace.md)                          |
| `sase workspace migrate`       | Opt-in move of adjacent checkouts to a managed root, with optional symlink transition and finalization. | [Workspace provider](workspace.md)                          |
| `sase git init`                | Initialize a bare-repo-backed git project.                                                              | [ProjectSpec](project_spec.md)                              |
| `sase mobile gateway start`    | Start the workstation-hosted mobile gateway.                                                            | [Mobile gateway](mobile_gateway.md)                         |
| `sase mobile agent-bridge`     | Fixed JSON bridge used by the mobile gateway for agent operations.                                      | [Mobile gateway](mobile_gateway.md)                         |
| `sase mobile helper-bridge`    | Fixed JSON bridge used by the mobile gateway for workflow helper operations.                            | [Mobile gateway](mobile_gateway.md)                         |

Operational commands are intentionally narrow. Helper bridges expose fixed JSON operations for editor and mobile
clients; they are not general shell or filesystem APIs.
