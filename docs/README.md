<!-- generated, do not edit -->
# Documentation map

## Home

- [Structured Agentic Software Engineering](index.md) — Run, review, and land work from parallel coding agents in one terminal workspace.

## Get started

- [Make and review a change](start/first-change.md) — Ask an agent for one small edit in SASE's demo workspace and inspect the resulting diff.
- [Run your first agent](start/first-run.md) — Launch a read-only request in SASE's demo workspace and inspect the result.
- [Get started](start/index.md) — Set up SASE, run an agent in its demo workspace, and review your first change.
- [Install and set up SASE](start/install.md) — Install SASE, confirm the command works, and check that an agent provider is ready.

## Guides

- [Add an existing repository](guides/add-existing-repository.md) — Register a repository you already have as a SASE project and initialize it.
- [Choose providers and models](guides/choose-providers-models.md) — Install a provider CLI, check authentication, and pick the model agents use.
- [Configure the essentials](guides/configure-essentials.md) — Set the handful of configuration values most setups change, and find the rest.
- [Diagnose problems with sase doctor](guides/diagnose-with-doctor.md) — Run the read-only diagnostic checks and act on what they report.
- [Find and replay an old prompt](guides/find-and-replay-prompt.md) — Search prompt history, inspect a past prompt, and launch it again safely.
- [Get automated code review](guides/get-automated-code-review.md) — Review each change automatically and apply the findings you accept.
- [Hand a result to another agent](guides/hand-a-result-to-another-agent.md) — Give a follow-up agent a transcript or specific artifact as task context.
- [Guides](guides/index.md) — Goal-titled how-to guides for setup, planning, daily work, and fixing problems.
- [Plan a multi-agent change](guides/plan-multi-agent-change.md) — Turn a large change into a reviewed plan whose phases agents work through.
- [Recover an interrupted agent](guides/recover-interrupted-agent.md) — Check whether an interrupted agent restarts itself, retry it, or revive it.
- [Reuse a prompt with macros](guides/reuse-prompt-with-macros.md) — Save a useful prompt as a named macro and use it in later agent runs.
- [Review and land a change](guides/review-and-land-change.md) — Inspect an agent's result and choose whether to commit, propose, or open a pull request.
- [Run agents in parallel](guides/run-agents-in-parallel.md) — Split independent work across agents and follow each run from the Agents tab.
- [Schedule recurring work](guides/schedule-recurring-work.md) — Run a check on a schedule with the scheduler and confirm each run.
- [Set up shell completion and your editor](guides/setup-completion-editor.md) — Complete sase commands with TAB and edit prompts with language assistance.
- [Unstick a queued agent](guides/unstick-queued-agent.md) — Tell capacity waits apart from holds and clear whichever blocks the agent.

## Concepts

- [Agents, sessions, and workspaces](concepts/agents.md) — How SASE gives delegated agent work an isolated place to run and a durable history.
- [Automation and human checkpoints](concepts/automation.md) — How SASE runs recurring work and keeps important decisions reviewable.
- [How SASE works](concepts/index.md) — The small set of ideas that explains how SASE keeps agent work organized and reviewable.
- [How changes land](concepts/landing.md) — How SASE carries agent changes through review and into version control.
- [Memory and agent instructions](concepts/memory.md) — How shared instructions and durable context guide agents across tasks.
- [Prompts, macros, and workflows](concepts/prompts.md) — How one task prompt can grow into reusable instructions and repeatable work.
- [Providers and models](concepts/providers.md) — How SASE connects agent work to coding-agent providers and models.
- [Work units](concepts/work-units.md) — How goals, plans, beads, and Patches represent outcomes, coordinated work, and reviewable changes.

## Reference

- [Agent Attachments and Image Previews](reference/agent-attachments.md) — Images and videos agents produce, and how sase's TUI previews them.
- [Agent auto-restart](reference/agent-auto-restart.md) — Recovery service for agents interrupted by a live update, and its limits.
- [Agent revive log](reference/agent-revive-log.md) — Audit records for TUI agent revival, and how to read them.
- [Agent clans](reference/agents/agent-clans.md) — Look up how parallel agent sessions are grouped and displayed.
- [Agent holds](reference/agents/agent-holds.md) — Admission barriers for agents and undispatched procs.
- [Agent-initiated launches](reference/agents/agent-launches.md) — Look up how an agent starts another session or workflow.
- [Agent sessions](reference/agents/agent-sessions.md) — Look up sequential agent sessions and their shared history.
- [Agent tribes](reference/agents/agent-tribes.md) — Look up how agents are grouped into persistent tribes.
- [Agent hood synchronization](reference/agents/hood-sync.md) — Look up shared hood privacy, layouts, publication, browsing, and recovery.
- [Agents and workspaces](reference/agents/index.md) — Look up agent sessions, initialization, synchronization, and workspace behavior.
- [Initialization](reference/agents/initialization.md) — Look up project initialization commands and the files they manage.
- [Machine initialization](reference/agents/machine-initialization.md) — Look up remote machine enrollment through SASE initialization.
- [Memory initialization](reference/agents/memory-initialization.md) — Look up how SASE initializes, lists, and audits agent memory.
- [Agent output variables](reference/agents/output-variables.md) — Publish and consume typed values from agent runs.
- [Service host initialization](reference/agents/service-host.md) — Look up how SASE initializes its per-user service host.
- [Workspaces](reference/agents/workspaces.md) — Look up workspace storage, repository commands, and workspace commands.
- [Artifact Links](reference/artifact-links.md) — Typed relationships between durable SASE artifacts.
- [Artifact References](reference/artifact-references.md) — Typed @kind:argument citations that expand in launch prompts.
- [Automation](reference/automation/index.md) — Reference pages for SASE notifications, scheduling, monitors, tools, mentors, and sudo requests.
- [Mentors](reference/automation/mentors.md) — Configure and use automated review mentors for Patches.
- [Monitor operations](reference/automation/monitor-operations.md) — Inspect, stop, and view monitors in the SASE TUI.
- [Monitors](reference/automation/monitors.md) — Start and supervise commands that outlive the SASE agent that launched them.
- [Notification CLI](reference/automation/notification-cli.md) — Command-line operations for listing and managing notifications.
- [Command-backed interaction gates](reference/automation/notification-gates.md) — Gate decisions, inputs, actions, and continuation behavior for SASE interactions.
- [Notification storage](reference/automation/notification-storage.md) — Storage behavior for SASE notifications.
- [Notification tags](reference/automation/notification-tags.md) — Notification tags and the colors and icons used in notification tabs.
- [Notification types](reference/automation/notification-types.md) — Notification payloads, fields, and silent notification behavior.
- [Notifications](reference/automation/notifications.md) — View, sort, mute, snooze, and receive notification updates in SASE.
- [Scheduler configuration](reference/automation/scheduler-configuration.md) — Global scheduler settings and the fields that configure routines.
- [Default scheduler routines](reference/automation/scheduler-default-routines.md) — The built-in routines that run background SASE maintenance and automation.
- [Scheduler description grammar](reference/automation/scheduler-description-grammar.md) — The grammar and style rules for scheduler routine descriptions.
- [Scheduler housekeeping](reference/automation/scheduler-housekeeping.md) — Tasks handled by the scheduler's housekeeping routine.
- [Scheduler jobs](reference/automation/scheduler-jobs.md) — Script jobs, manual runs, job history, service views, and job-agent records.
- [Scheduler](reference/automation/scheduler.md) — Scheduler commands, lifecycle, recovery, state, and SASE integration.
- [Sudo requests](reference/automation/sudo.md) — Request, review, and recover privileged commands run on behalf of SASE agents.
- [Named tools and ToolRuns](reference/automation/tools.md) — Declare named tools and run commands with retained output and evidence.
- [CLI behavior notes](reference/cli-notes.md) — Root command behavior and links to CLI command and subsystem references.
- [sase agent-cli](reference/cli/agent-cli.md) — Inspect the coding-agent CLIs supported by SASE and install or update installs whose management method can be identified safely.
- [sase agent](reference/cli/agent.md) — Inspect and manage agents across projects.
- [sase artifact](reference/cli/artifact.md) — Create, discover, inspect, resolve, open, and repair indexed artifacts.
- [sase autonomy](reference/cli/autonomy.md) — Inspect the core-owned %auto autonomy record: predict each gate decision exactly (`explain`), list the built-in profiles (`list`), read the host decision log…
- [sase axe](reference/cli/axe.md) — Alias of `sase scheduler`, plus the routine and job tree
- [sase bead](reference/cli/bead.md) — Lightweight git-native issue tracking
- [sase chat](reference/cli/chat.md) — Discover and inspect prior agent chat transcripts
- [sase comments](reference/cli/comments.md) — Preview mentor comments from JSON (reads from stdin or file)
- [sase completion](reference/cli/completion.md) — Generate native shell-completion scripts from the live sase argparse tree, install them where the shell will actually load them, and inspect the structural…
- [sase config](reference/cli/config.md) — Inspect merged configuration, layers, and mentor profile matching
- [sase core](reference/cli/core.md) — Inspect the required sase_core_rs Rust extension
- [sase disk](reference/cli/disk.md) — Inspect SASE-owned disk usage and delegate cleanup to each owner.
- [sase doctor](reference/cli/doctor.md) — Run fast, read-only diagnostics for the active SASE runtime, configuration, and project checkout.
- [sase editor](reference/cli/editor.md) — Run editor integration helpers
- [sase file-history](reference/cli/file-history.md) — Inspect and modify the file-reference history
- [sase file-hook](reference/cli/file-hook.md) — Inspect non-gating commands configured under `file_hooks` and the producer audit history for matching, dispatch, and pre-run failures.
- [sase file](reference/cli/file.md) — Filesystem completion helpers (consumed by editor integrations)
- [sase final](reference/cli/final.md) — Inspect host-owned finalizer instances, provider provenance, and the current turn's declaration obligations.
- [sase flag](reference/cli/flag.md) — Inspect the code-owned SASE feature-flag registry, persist a machine-local enable or disable choice, and scaffold a new flag plus its dedicated removal bead.
- [sase gate](reference/cli/gate.md) — Create durable command-backed gates from versioned JSON specifications, inspect what they ask for, run their repeatable actions, answer them headlessly, and…
- [sase goal](reference/cli/goal.md) — Create, list, show, edit, drop, reopen, merge, and check durable goal records.
- [CLI command groups](reference/cli/index.md) — Generated CLI reference, one page per sase command group.
- [sase init](reference/cli/init.md) — Check and initialize SASE-managed resources.
- [sase instructions](reference/cli/instructions.md) — Inspect agent instruction documents.
- [sase launch](reference/cli/launch.md) — Resolve pending launch approval requests created before detached agents are spawned.
- [sase logs](reference/cli/logs.md) — Collect logs and runtime data for a date range into a pack directory
- [sase lsp](reference/cli/lsp.md) — Start the SASE macro language server.
- [sase machine](reference/cli/machine.md) — Manage viewer-local aliases for enrolled remote machines.
- [sase macro](reference/cli/macro.md) — Expand and visualize macro workflows
- [sase memory](reference/cli/memory.md) — Inspect SASE memory context.
- [sase migrate](reference/cli/migrate.md) — Temporary offline migration kit for the canonical-only cutover.
- [sase mobile](reference/cli/mobile.md) — Run mobile integration helpers
- [sase monitor](reference/cli/monitor.md) — Hand a slow command off to a detached supervisor that runs as a real agent session member, with streaming output, a timeout, and an optional follow-up agent.
- [sase notify](reference/cli/notify.md) — Create and inspect raw notifications.
- [sase pager](reference/cli/pager.md) — Open artifact references, file paths, or stdin as one navigable SASE pager document.
- [sase patch](reference/cli/patch.md) — Inspect and maintain Patch lifecycle records.
- [sase path](reference/cli/path.md) — Print well-known sase paths (for editor integration)
- [sase pipe](reference/cli/pipe.md) — End this agent's turn and continue the run as the next agent session member in the same workspace, with the prompt you write.
- [sase plan](reference/cli/plan.md) — Review the plan pipeline, approve or reject pending proposals from the Patch, inspect SDD prompt/plan links, submit a new plan for review, search SDD and…
- [sase plugin](reference/cli/plugin.md) — Discover every SASE plugin that exists by treating the GitHub `sase--plugin` repository topic as the canonical registry.
- [sase proc](reference/cli/proc.md) — Inspect and run SASE procs.
- [sase project](reference/cli/project.md) — Inspect project lifecycle state and the current project.
- [sase prompt](reference/cli/prompt.md) — Inspect, search, and reuse previously submitted agent prompts
- [sase questions](reference/cli/questions.md) — Ask the user questions (used by /sase_questions skill)
- [sase repo](reference/cli/repo.md) — Initialize, inspect, and resolve repositories known by SASE.
- [sase repro](reference/cli/repro.md) — Capture and replay reproduction bundles
- [sase restore](reference/cli/restore.md) — Restore a reverted Patch by re-applying its diff and creating a new PR
- [sase revert](reference/cli/revert.md) — Revert a Patch by pruning its PR and archiving the diff
- [sase revive-log](reference/cli/revive-log.md) — Show recent agent revive attempts from the audit log
- [sase run](reference/cli/run.md) — Launch a detached background coding-agent run from a prompt, macro, or workflow.
- [sase scheduler](reference/cli/scheduler.md) — Control the SASE scheduler.
- [sase screenshot](reference/cli/screenshot.md) — Launch or reuse a real `sase tui` in tmux, drive it with keypresses and typed text, ask the live app to export SVG, and rasterize that SVG to PNG.
- [sase service](reference/cli/service.md) — Manage the per-machine SASE service host.
- [sase skill](reference/cli/skill.md) — Inspect, initialize, and audit generated SASE skills.
- [sase snippet](reference/cli/snippet.md) — Inspect or update the effective snippet catalog for a project.
- [sase stats](reference/cli/stats.md) — Show Admin Center Statistics views from the command line.
- [sase stitch](reference/cli/stitch.md) — Dispatch a commit, proposal, or pull request, or show the cross-repository stitch timeline for the primary repo and configured linked repos.
- [sase sudo](reference/cli/sudo.md) — Create typed sudo request gates and answer them from a controlling terminal through the dedicated sudo runner.
- [sase telemetry](reference/cli/telemetry.md) — Inspect locally persisted telemetry.
- [sase tmux-agent](reference/cli/tmux-agent.md) — Launch an interactive agent CLI in a new tmux window.
- [sase tool](reference/cli/tool.md) — List, run, and inspect project-owned named tools and the machine-local ToolRun ledger.
- [sase tui](reference/cli/tui.md) — Open sase's TUI for agents, Patches, artifacts, notifications, and Services
- [sase update](reference/cli/update.md) — Upgrade sase and every installed sase plugin together, in one atomic operation, by delegating to `uv tool upgrade sase`.
- [sase usage](reference/cli/usage.md) — Inspect cached provider subscription-usage observations and submit explicit refreshes.
- [sase validate](reference/cli/validate.md) — Run SASE initialization and SDD validation checks
- [sase var](reference/cli/var.md) — Inspect historical output variables, retrieve a snapshot or selector values, or set variables on the current SASE agent run.
- [sase version](reference/cli/version.md) — Show the exact SASE host, Rust core, and plugin packages used by this process.
- [sase workspace](reference/cli/workspace.md) — Inspect and manage managed workspace checkouts
- [ACE configuration behavior](reference/config/ace-behavior.md) — Behavior settings for the SASE Admin Center and other TUI surfaces.
- [ACE keymap configuration](reference/config/ace-keymap-configuration.md) — Configuration behavior for SASE Admin Center and TUI keymaps.
- [ACE prompt configuration](reference/config/ace-prompts.md) — Prompt completion, snippets, prompt history, and agent deck settings.
- [Agent and runner configuration](reference/config/agents-and-runners.md) — Configuration for agent admission, runner capacity, and lifecycle behavior.
- [Agents and runners configuration](reference/config/agents.md) — Agent launch, completion, capacity, restart, and process-scope settings.
- [Artifact configuration](reference/config/artifacts.md) — Configuration behavior for agent artifacts and artifact references.
- [Automation configuration behavior](reference/config/automation-behavior.md) — Configuration for SDD, beads, and external issue mirroring.
- [Automation and work tracking configuration](reference/config/automation.md) — Beads, goals, gates, SDD, and related automation policy.
- [Core configuration behavior](reference/config/core-behavior.md) — Runtime behavior for core identity, managed instructions, and machine settings.
- [Core and identity configuration](reference/config/core.md) — Repository ownership, identity, and machine-wide configuration switches.
- [Display and reading configuration](reference/config/display-and-reading.md) — Configuration for Markdown rendering, paging, and reading surfaces.
- [Feature flag configuration](reference/config/feature-flags.md) — Configuration and persisted state for SASE feature flags.
- [Configuration files and merging](reference/config/files-and-merging.md) — Configuration file locations, owner identity, merge precedence, and storage layout.
- [Finalizer configuration](reference/config/finalizers.md) — Configuration for commit hooks and post-run finalizers.
- [Configuration reference](reference/config/index.md) — Generated configuration keys, types, defaults, and allowed values.
- [Integration configuration behavior](reference/config/integrations-behavior.md) — Configuration behavior for chat and mobile integrations.
- [Integrations and telemetry configuration](reference/config/integrations.md) — Chat, mobile access, and local telemetry settings.
- [LLM provider behavior configuration](reference/config/llm-provider-behavior.md) — Provider selection, usage limits, retries, and execution budgets.
- [LLM provider configuration](reference/config/llm-provider.md) — Provider selection, model defaults, and model execution policy.
- [Memory and instructions configuration](reference/config/memory.md) — Project memory, generated instruction templates, and their compatibility aliases.
- [Monitor configuration](reference/config/monitor-behavior.md) — Settings for monitor execution, wrappers, and continuation.
- [Configuration keys needing descriptions](reference/config/needs-description.md) — Schema paths that do not yet have a description.
- [Prompt and tool configuration](reference/config/prompts-and-tools.md) — Configuration for hooks, plugins, mentors, macros, and named tools.
- [Prompts and tools configuration](reference/config/prompts.md) — Macros, named tools, plugins, hooks, and mentor selection.
- [Repository configuration behavior](reference/config/repositories-behavior.md) — Repository lists, dispatch, VCS selection, and completion settings.
- [Repositories and version control configuration](reference/config/repositories.md) — Repository relationships, VCS providers, dispatch, commits, and workspace configuration.
- [Runtime and storage configuration](reference/config/runtime-and-storage.md) — Configuration for processes, services, local storage, and telemetry.
- [Runtime and stored data configuration](reference/config/runtime.md) — Process history, service hosting, artifacts, disk use, and reading surfaces.
- [Scheduler configuration behavior](reference/config/scheduler-behavior.md) — AXE scheduler settings and their runtime behavior.
- [Scheduler configuration](reference/config/scheduler.md) — AXE scheduler routines, jobs, and execution limits.
- [TUI configuration](reference/config/tui.md) — Settings for SASE's terminal interface and its configurable panes.
- [Workspace configuration behavior](reference/config/workspace-behavior.md) — Configuration for workspace directory layout and lifecycle.
- [Content layout](reference/content-layout.md) — Canonical paths for project and home SASE content.
- [Design decisions](reference/design-decisions.md) — Why SASE works this way, generated from the decisions memory web.
- [Diagnostics and support reports](reference/diagnostics.md) — Read-only validation, diagnostics, logs, and support bundle behavior.
- [SASE disk cleanup](reference/disk-cleanup.md) — Inspect SASE-created bytes and delegate cleanup to the owning subsystem.
- [Environment variables](reference/environment-variables.md) — Environment variables that configure providers, SDD, plugins, runtime, and workspaces.
- [Glossary](reference/glossary.md) — Every SASE term, generated from the glossary memory web.
- [Reference](reference/index.md) — Look up exact SASE facts here, generated from code where possible.
- [Shell Completion](reference/integrations/completion.md) — Native zsh, bash, and fish completion from the live sase argparse tree.
- [Editor Integration](reference/integrations/editor.md) — Language-server and helper-bridge surfaces for prompt and macro editing.
- [Integrations](reference/integrations/index.md) — Look up plugins, editor, completion, mobile, and remote dispatch surfaces.
- [Mobile gateway](reference/integrations/mobile-gateway.md) — Look up pairing, push hints, storage, and private remote access.
- [Command plugins](reference/integrations/plugins-commands.md) — Look up how plugins mount top-level sase commands.
- [Installing and updating plugins](reference/integrations/plugins-update.md) — Look up sase update and plugin install, update, and uninstall.
- [Plugins](reference/integrations/plugins.md) — Look up plugin groups, the catalog, installation, and disable switches.
- [Remote Dispatch Runbook](reference/integrations/remote-dispatch.md) — Enroll a remote machine and launch agents on it with %dispatch.
- [Macro arguments and typed inputs](reference/macros/arguments.md) — Argument syntax, input types, defaults, and rendered output shapes.
- [Built-in and configured macros](reference/macros/built-ins.md) — Built-in macros, configuration-defined macros, and local macro files.
- [Macro CLI and editor support](reference/macros/cli-and-editor.md) — Macro command behavior and editor language-server features.
- [Directive composition and fan-out](reference/macros/directive-composition.md) — Directives for review, follow-up, repetition, and prompt fan-out.
- [Launch directives](reference/macros/directive-launch.md) — Directives for agent identity, launch settings, and queue admission.
- [Directive syntax and completion](reference/macros/directive-syntax.md) — Directive forms, completion behavior, and model and dispatch settings.
- [Macro directives](reference/macros/directives.md) — The generated catalog of prompt directives and their syntax.
- [Macro discovery order](reference/macros/discovery-order.md) — File-backed macro and workflow locations in lookup order.
- [Macro discovery](reference/macros/discovery.md) — How SASE finds macros, workflows, skills, and memory references.
- [Macro fields](reference/macros/fields.md) — The snippet, skill, and memory fields available in macro front matter.
- [Macro Template Reference](reference/macros/index.md) — Reference pages for macro syntax, directives, fields, and workflows.
- [Multi-agent prompts and workflows](reference/macros/multi-agent-prompts.md) — Prompt segments, output variables, macro swarms, and workflows.
- [Macro files and reference syntax](reference/macros/reference-syntax.md) — Macro file format, reference forms, workspace references, and project tags.
- [Macro tags](reference/macros/tags.md) — Available macro tags, their definitions, and tag-based lookup.
- [Macro template rendering](reference/macros/templating.md) — Template context, placeholders, protected content, aliases, and expansion.
- [Macro troubleshooting](reference/macros/troubleshooting.md) — Common macro expansion problems and ways to diagnose them.
- [Memory History](reference/memory/history.md) — How SASE records and displays changes to memory notes and instruction documents.
- [Memory](reference/memory/index.md) — Lookup pages for durable memory, instruction bundles, and memory history.
- [Instruction bundles](reference/memory/instruction-bundles.md) — How SASE instruction bundles are previewed and how providers report delivery behavior.
- [Memory](reference/memory/memory.md) — How SASE stores, composes, audits, and links durable memory context.
- [Prompt History and Draft Recovery](reference/prompt-history.md) — Recorded prompts, replay, draft recovery, and the sase prompt command group.
- [Installing and authenticating agent CLIs](reference/providers/agent-clis.md) — Provider CLIs that SASE can install, authenticate, inspect, and update safely.
- [Antigravity provider](reference/providers/agy.md) — Antigravity CLI command construction, model mapping, and provider-specific behavior.
- [Claude Code provider](reference/providers/claude.md) — Claude Code command construction, model mapping, and provider-specific behavior.
- [Codex CLI provider](reference/providers/codex.md) — Codex command construction, model mapping, planning, and provider-specific behavior.
- [Provider configuration](reference/providers/configuration.md) — Configuration fields and command-line options that affect provider invocation.
- [Grok Build provider](reference/providers/grok.md) — Grok Build command construction, event streaming, and provider-specific behavior.
- [Providers and models](reference/providers/index.md) — Lookup pages for provider integrations, model selection, routing, and usage.
- [Models and aliases](reference/providers/models.md) — Model names, reasoning effort, model tiers, and aliases used for provider routing.
- [Muse Code provider](reference/providers/muse.md) — Muse Code command construction, event streaming, and provider-specific behavior.
- [OpenCode provider](reference/providers/opencode.md) — OpenCode command construction, model mapping, and provider-specific behavior.
- [External provider plugins](reference/providers/plugins.md) — How external plugins extend SASE's LLM provider registry.
- [Qwen Code provider](reference/providers/qwen.md) — Qwen Code command construction, authentication, and provider-specific behavior.
- [Provider retry and fallback](reference/providers/retry-and-fallback.md) — Retry defaults, fallback behavior, and how provider failures affect invocations.
- [Provider routing](reference/providers/routing.md) — Per-prompt selection and temporary provider or model routing controls.
- [Provider usage](reference/providers/usage.md) — Subscription usage reporting and automatic provider disabling at usage limits.
- [Query Language Reference](reference/query-language.md) — Boolean expressions that filter Patches in sase tui and other Patch queries.
- [Runner slots](reference/runner-slots.md) — How runner capacity admits queued agents, and what waiting.json records.
- [SASE Admin Center](reference/tui/admin-center.md) — Navigation, sections, and editor behavior in the SASE Admin Center.
- [Agent row glyphs](reference/tui/agent-row-glyphs.md) — Glyphs, markers, and badges on Agents tab rows.
- [Agent statuses](reference/tui/agent-statuses.md) — Agent, wait, and completion statuses on the Agents tab.
- [Agent workflows](reference/tui/agent-workflows.md) — Plan workflows, approvals, holds, and retries on the Agents tab.
- [Agents tab LLM calls and tool runs](reference/tui/agents-deck-panels.md) — LLM call and tool run panels on the Agents tab.
- [Agents tab main deck](reference/tui/agents-main-deck.md) — The main deck view, detail zoom, and the node rail.
- [Agents tab grouping](reference/tui/agents-tab-grouping.md) — Group banners, folding, and grouping modes on the Agents tab.
- [Agents tab search and modes](reference/tui/agents-tab-modes.md) — Search, leader, bang, and copy modes on the Agents tab.
- [Agents tab panels](reference/tui/agents-tab-panels.md) — Clan, session, neighbor, and tribe panels on the Agents tab.
- [Agents tab](reference/tui/agents-tab.md) — Tabs, keys, lists, and actions on the sase TUI Agents tab.
- [Artifacts tab](reference/tui/artifacts-tab.md) — Artifact links, Patches keybindings, mentor comment stats, and the PR origin chip.
- [Files and preview](reference/tui/files-and-preview.md) — The Files pane, Preview reader, and Agents tab Archive in the sase TUI.
- [Filtering](reference/tui/filtering.md) — Query filtering on the Agents, Patches, Commits, Beads, and Plans TUI panes.
- [Finders](reference/tui/finders.md) — The Jump All modal, jump back, and the Node Finder in the sase TUI.
- [Global controls](reference/tui/global-controls.md) — Global keys, custom keymaps, the command palette, the command line, and auto-refresh.
- [TUI](reference/tui/index.md) — Reference pages for the sase TUI tabs, prompt, Launch Control, pager, and global controls.
- [TUI keymaps](reference/tui/keymaps.md) — Default configurable key bindings for SASE's terminal interface.
- [Launch Control overrides](reference/tui/launch-control-overrides.md) — Temporary overrides, persistent alias edits, and examples in sase TUI Launch Control.
- [Launch Control](reference/tui/launch-control.md) — Launch Control keys for usage, effort, capacity, routing, drain, tmux Agent, and alias history.
- [Launching the TUI](reference/tui/launching.md) — How to start sase tui, including CLI options, screenshots, and clipboard transports.
- [Machines, statistics, and tools](reference/tui/machines-and-tools.md) — Machines, Statistics, and Tools tabs plus the Config Flags pane in the sase TUI.
- [Notifications modal](reference/tui/notifications-modal.md) — The notifications modal, snooze scheduling, notification actions, and toasts.
- [SASE Pager](reference/tui/pager.md) — Open artifact references, file paths, or stdin in the SASE link-traversing pager.
- [Procs tab](reference/tui/procs-tab.md) — The Procs tab layout, status icons, monitors, durable procs, filtering, and keys.
- [Projects tab](reference/tui/projects-tab.md) — The Projects tab, adding and initializing projects, and the current-project indicator.
- [Prompt completion panels](reference/tui/prompt-completion-panels.md) — Glossary, memory, snippets, repo-name, and spellcheck completion panels in the sase TUI prompt.
- [Prompt completion](reference/tui/prompt-completion.md) — Token completion in the sase TUI prompt widget, including next-word prediction.
- [Prompt input](reference/tui/prompt-input.md) — Insert mode, alt-brace syntax, macro editing, search, and launch-target picking in the sase TUI prompt widget.
- [Prompt modes](reference/tui/prompt-modes.md) — NORMAL and Visual mode keys for the sase TUI prompt input widget.
- [Prompt stacks](reference/tui/prompt-stacks.md) — Multi-agent prompt stacks, stash, and trash in the sase TUI prompt widget.
- [Prompts overlay](reference/tui/prompts-overlay.md) — History, stash, and trash in the sase TUI Prompts overlay (the prompt-history modal).
- [Query system](reference/tui/query-system.md) — Editing, saving, and recalling queries in the sase TUI.
- [Services tab](reference/tui/services-tab.md) — Services tab sidebar, description panel, job results, and control keys.
- [Snippets](reference/tui/snippets.md) — Prompt snippets, variables, aliases, and the Macro Browser in the sase TUI.
- [Tabs and panes](reference/tui/tabs-and-panes.md) — Top-level TUI tabs, Artifacts panes, navigation, copy mode, marks, and Beads.
- [Updates tab](reference/tui/updates-tab.md) — The Updates tab for SASE core, plugins, and agent CLI updates from the TUI.
- [Agent hood synchronization upgrades](reference/upgrading/agents-sidecar.md) — Upgrade notes for retired agent hood synchronization formats.
- [Automation migration notes](reference/upgrading/automation.md) — Upgrade notes for scheduler naming, monitor hand-off, and gate contracts.
- [Configuration migration notes](reference/upgrading/configuration.md) — Migration steps for configuration keys, file hooks, repositories, and SDD storage.
- [Content layout migration](reference/upgrading/content-layout.md) — Migration steps and compatibility behavior for SASE content paths.
- [Upgrading](reference/upgrading/index.md) — Upgrade and history notes, organized by area with the newest notes first.
- [Local state cutover](reference/upgrading/local-state.md) — The temporary offline kit for moving legacy local state into canonical locations.
- [Macro migration notes](reference/upgrading/macros.md) — Migration notes for macro names, prompt fields, and launch syntax.
- [Provider migration notes](reference/upgrading/providers.md) — Historical compatibility notes for VCS commands, provider metadata, and model selection.
- [TUI migration notes](reference/upgrading/tui.md) — Upgrade notes for sase tui command names, aliases, query tokens, and stored layouts.
- [Work unit migration notes](reference/upgrading/work-units.md) — Compatibility notes for bead, plan, Patch, and ProjectSpec formats.
- [Workspace upgrades](reference/upgrading/workspaces.md) — Upgrade notes for the managed workspace root and adjacent checkouts.
- [Commit workflows](reference/vcs/commit-workflows.md) — Look up commit, proposal, and pull request workflow behavior.
- [Version control](reference/vcs/index.md) — Look up SASE's version control providers, workflows, and repository behavior.
- [VCS providers](reference/vcs/providers.md) — Look up provider selection, repository operations, and troubleshooting.
- [Bead artifacts](reference/work-units/bead-artifacts.md) — How beads refer to plans, research, and other artifacts.
- [Bead attachments](reference/work-units/bead-attachments.md) — Attachment storage, visibility, and troubleshooting for bead records.
- [Reading beads](reference/work-units/bead-cli-inspection.md) — Commands for adding notes and reading detailed bead records.
- [Bead CLI queries](reference/work-units/bead-cli-query.md) — Commands for listing, searching, and checking SASE bead records.
- [Bead CLI records](reference/work-units/bead-cli-records.md) — Commands for creating, updating, closing, and synchronizing bead records.
- [Bead CLI](reference/work-units/bead-cli.md) — An overview of the commands for reading and managing SASE beads.
- [Bead lifecycles](reference/work-units/bead-lifecycles.md) — The status transitions for SASE beads, flag beads, and bead claims.
- [Bead mirroring](reference/work-units/bead-mirroring.md) — How SASE beads can mirror issues from an external tracker.
- [Bead pages](reference/work-units/bead-pages.md) — The generated pages that present bead records and their relationships.
- [Bead storage](reference/work-units/bead-storage.md) — The bead store layout, event log, synchronization, and checkout source of truth.
- [Bead triage](reference/work-units/bead-triage.md) — How bead dependencies, follow-ups, corroboration, and snoozes are handled.
- [Bead TUI integration](reference/work-units/bead-tui.md) — How SASE's TUI connects bead records with plans and task work.
- [Starting bead work](reference/work-units/bead-work.md) — How `sase bead work` resolves plans and starts assigned bead work.
- [Beads](reference/work-units/beads.md) — Bead identities, types, and the data model for work in SASE.
- [Work tracking CLI workflows](reference/work-units/cli-workflows.md) — How CLI workflows connect beads, plans, goals, projects, and Patches.
- [Goals](reference/work-units/goals.md) — Durable outcome records and their lifecycle, storage, and freshness.
- [Work units](reference/work-units/index.md) — Reference pages for SASE's beads, plans, goals, Patches, and ProjectSpec files.
- [Patches](reference/work-units/patches.md) — The fields, format, and lifecycle of a SASE Patch review record.
- [Plan commands](reference/work-units/plan-cli.md) — The SASE CLI commands and bead integration for saved plans.
- [Plan configuration](reference/work-units/plan-execution.md) — Configuration and multi-workspace behavior for SASE plan execution.
- [Plan format](reference/work-units/plan-format.md) — The fields, validation rules, and decision sections used in SASE plans.
- [Plans](reference/work-units/plans.md) — Spec-Driven Development storage, artifacts, and plan lifecycle in SASE.
- [ProjectSpec](reference/work-units/project-spec.md) — The shared project-level file for project metadata and Patch records.
- [Workflow Specification](reference/workflows.md) — YAML workflow files, step types, inputs, and execution behavior.

## Contribute

- [Acknowledgements](contribute/acknowledgements.md) — People, projects, and research that shaped SASE.
- [Agent sidecar synchronization internals](contribute/agents-sidecar-sync.md) — Synchronization and reconciliation internals for agent sidecars.
- [Architecture](contribute/architecture.md) — Architecture internals, runtime flow, state ownership, and provider boundaries inside SASE.
- [Artifacts pane contract](contribute/artifacts-pane-contract.md) — ArtifactsPaneContract is the host-owned record that decides what a pane can do before widgets, keybindings, or document providers run.
- [Artifacts pane visual grammar](contribute/artifacts-pane-visual-grammar.md) — Every configured Artifacts pane renders through one shared, contract-driven shell.
- [Commit workflow orchestrator](contribute/commit-workflow-orchestrator.md) — Contributor internals for commit workflow orchestration and finalization.
- [Development](contribute/development.md) — This page orients contributors working in the sase repository.
- [Fakey Testing Provider](contribute/fakey.md) — fakey is a deterministic fake agent CLI bundled with SASE.
- [Contribute](contribute/index.md) — Contributor guides, internals, contracts, and runbooks for SASE.
- [Instruction bundle internals](contribute/instruction-bundle-internals.md) — Manifest, storage, cache, and delivery contracts for generated instruction bundles.
- [Integration APIs](contribute/integration-apis.md) — SASE exposes a small set of Python helpers for external plugins, chat clients, mobile clients, and editor integrations.
- [LLM invocation internals](contribute/llm-invocation.md) — Internal provider architecture, prompt processing, subprocess handling, and invocation lifecycle.
- [Mobile gateway API](contribute/mobile-gateway-api.md) — Host-bridge commands, events, and API contract for the mobile gateway.
- [Mobile MVP Runbook](contribute/mobile-mvp-runbook.md) — This runbook covers the private Android MVP that connects a phone to a workstation-hosted SASE mobile gateway.
- [Prepared monitor completion](contribute/monitor-completion.md) — Internal details for opt-in no-new prepared monitor completion.
- [sase tui Performance Runbook](contribute/perf-runbook.md) — This runbook explains how to capture and compare performance data for sase's TUI, the sase tui terminal user interface.
- [Plugin API](contribute/plugin-api.md) — Contributor contract for discovering and writing SASE plugins.
- [Reader testing](contribute/reader-testing.md) — How to run an observed reader round and turn the results into doc changes.
- [Rust Backend (sase_core_rs)](contribute/rust-backend.md) — A subset of sase's core APIs is served by a Rust extension distributed as sase-core-rs on PyPI and built from the sibling sase-core repo.
- [SDD Storage](contribute/sdd-storage.md) — The workspace provider owns SDD placement, while projects select a store beneath it.
- [Telemetry](contribute/telemetry.md) — SASE records debugging and health metric history locally.
- [Tool run receipts](contribute/tool-run-receipts.md) — Internal receipt policy and verification details for recorded tool runs.
- [TUI rendering](contribute/tui-rendering.md) — Tab bar display, file panel rendering, and the image preview foundation in the sase TUI.
- [VCS provider API](contribute/vcs-provider-api.md) — Contributor contract for implementing and selecting VCS providers.
- [Workspace provider internals](contribute/workspace-provider.md) — Provider APIs, hooks, and ownership rules for workspace implementations.
- [Writing docs](contribute/writing-docs.md) — The sase.sh documentation contract for humans and agents.

## Blog

- [SASE Blog](blog/index.md) — Essays on structured agentic software engineering and the SASE launch post.
- [SASE: Structured Agentic Software Engineering](blog/posts/structured-agentic-software-engineering.md) — From a tmux full of coding agents to an operating layer around them: agent CLIs, Macros, sase's TUI Agents tab, and a practical install path for SASE.

## Compatibility

- [sase's TUI User Guide](ace.md) — This page has moved to its new home.
- [Agent Clans, Sessions, and Tribes](agent_sessions.md) — This page has moved to its new home.
- [Agent Hood Synchronization](agents_sidecar.md) — This page has moved to its new home.
- [Scheduler — Background Automation](axe.md) — This page has moved to its new home.
- [Bead Issue Tracking](beads.md) — This page has moved to its new home.
- [CLI Reference](cli.md) — This page has moved to its new home.
- [Commit Workflows](commit_workflows.md) — This page has moved to its new home.
- [Configuration Reference](configuration.md) — This page has moved to its new home.
- [Canonical SASE Content Layout](content_layout.md) — This page has moved to its new home.
- [Initialization](init.md) — This page has moved to its new home.
- [Instruction Bundles](instruction_bundles.md) — This page has moved to its new home.
- [LLM Provider Integration](llms.md) — This page has moved to its new home.
- [Macro Template Reference](macros.md) — This page has moved to its new home.
- [Mobile Gateway](mobile_gateway.md) — This page has moved to its new home.
- [Monitors](monitors.md) — This page has moved to its new home.
- [Notifications](notifications.md) — This page has moved to its new home.
- [Plugin System](plugins.md) — This page has moved to its new home.
- [Rust Backend (sase_core_rs)](rust_backend.md) — This page has moved to its new home.
- [Spec-Driven Development (SDD)](sdd.md) — This page has moved to its new home.
- [Named Tools and ToolRuns](tool.md) — This page has moved to its new home.
- [VCS Provider Reference](vcs.md) — This page has moved to its new home.
- [Workspace Provider Reference](workspace.md) — This page has moved to its new home.

## Moved pages

| Old path | New home |
| --- | --- |
| `/instruction_inventory/` | [`/instruction_bundles/`](instruction_bundles.md) |
| `/architecture/` | [`/contribute/architecture/`](contribute/architecture.md) |
| `/getting_started/` | [`/start/`](start/index.md) |
| `/agent_auto_restart/` | [`/reference/agent-auto-restart/`](reference/agent-auto-restart.md) |
| `/troubleshooting/runner-slots/` | [`/reference/runner-slots/`](reference/runner-slots.md) |
| `/troubleshooting/agent-revival/` | [`/reference/agent-revive-log/`](reference/agent-revive-log.md) |
| `/acknowledgements/` | [`/contribute/acknowledgements/`](contribute/acknowledgements.md) |
| `/content_layout/` | [`/reference/upgrading/`](reference/upgrading/index.md) |
| `/ace/` | [`/reference/tui/`](reference/tui/index.md) |
| `/configuration/` | [`/reference/config/`](reference/config/index.md) |
| `/development/` | [`/contribute/development/`](contribute/development.md) |
| `/rust_backend/` | [`/contribute/rust-backend/`](contribute/rust-backend.md) |
| `/fakey/` | [`/contribute/fakey/`](contribute/fakey.md) |
| `/telemetry/` | [`/contribute/telemetry/`](contribute/telemetry.md) |
| `/perf_runbook/` | [`/contribute/perf-runbook/`](contribute/perf-runbook.md) |
| `/mobile_mvp_runbook/` | [`/contribute/mobile-mvp-runbook/`](contribute/mobile-mvp-runbook.md) |
| `/integrations/` | [`/contribute/integration-apis/`](contribute/integration-apis.md) |
| `/artifacts_pane_contract/` | [`/contribute/artifacts-pane-contract/`](contribute/artifacts-pane-contract.md) |
| `/artifacts_pane_visual_grammar/` | [`/contribute/artifacts-pane-visual-grammar/`](contribute/artifacts-pane-visual-grammar.md) |
| `/sdd_storage/` | [`/contribute/sdd-storage/`](contribute/sdd-storage.md) |
| `/agent_providers/` | [`/reference/providers/agent-clis/`](reference/providers/agent-clis.md) |
| `/memory_history/` | [`/reference/memory/history/`](reference/memory/history.md) |
| `/llms/` | [`/reference/providers/`](reference/providers/index.md) |
| `/instruction_bundles/` | [`/reference/memory/instruction-bundles/`](reference/memory/instruction-bundles.md) |
| `/memory/` | [`/reference/memory/memory/`](reference/memory/memory.md) |
| `/notifications/` | [`/reference/automation/notifications/`](reference/automation/notifications.md) |
| `/axe/` | [`/reference/automation/scheduler/`](reference/automation/scheduler.md) |
| `/monitors/` | [`/reference/automation/monitors/`](reference/automation/monitors.md) |
| `/tool/` | [`/reference/automation/tools/`](reference/automation/tools.md) |
| `/mentors/` | [`/reference/automation/mentors/`](reference/automation/mentors.md) |
| `/sudo/` | [`/reference/automation/sudo/`](reference/automation/sudo.md) |
| `/macros/` | [`/reference/macros/`](reference/macros/index.md) |
| `/workflow_spec/` | [`/reference/workflows/`](reference/workflows.md) |
| `/goals/` | [`/reference/work-units/goals/`](reference/work-units/goals.md) |
| `/change_spec/` | [`/reference/work-units/patches/`](reference/work-units/patches.md) |
| `/project_spec/` | [`/reference/work-units/project-spec/`](reference/work-units/project-spec.md) |
| `/beads/` | [`/reference/work-units/`](reference/work-units/index.md) |
| `/sdd/` | [`/reference/work-units/`](reference/work-units/index.md) |
| `/agent_sessions/` | [`/reference/agents/`](reference/agents/index.md) |
| `/workspace/` | [`/reference/agents/`](reference/agents/index.md) |
| `/agents_sidecar/` | [`/reference/agents/`](reference/agents/index.md) |
| `/init/` | [`/reference/agents/`](reference/agents/index.md) |
| `/vcs/` | [`/reference/vcs/`](reference/vcs/index.md) |
| `/commit_workflows/` | [`/reference/vcs/`](reference/vcs/index.md) |
| `/plugins/` | [`/reference/integrations/`](reference/integrations/index.md) |
| `/mobile_gateway/` | [`/reference/integrations/`](reference/integrations/index.md) |
| `/editor/` | [`/reference/integrations/editor/`](reference/integrations/editor.md) |
| `/completion/` | [`/reference/integrations/completion/`](reference/integrations/completion.md) |
| `/remote_dispatch/` | [`/reference/integrations/remote-dispatch/`](reference/integrations/remote-dispatch.md) |
| `/query_language/` | [`/reference/query-language/`](reference/query-language.md) |
| `/agent_images/` | [`/reference/agent-attachments/`](reference/agent-attachments.md) |
| `/prompt/` | [`/reference/prompt-history/`](reference/prompt-history.md) |
| `/artifact_references/` | [`/reference/artifact-references/`](reference/artifact-references.md) |
| `/artifact_links/` | [`/reference/artifact-links/`](reference/artifact-links.md) |
| `/pager/` | [`/reference/tui/pager/`](reference/tui/pager.md) |
| `/cli/` | [`/reference/cli/`](reference/cli/index.md) |
