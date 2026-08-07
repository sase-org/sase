# Acknowledgements

## Boris' Method

Before sase existed, [Boris Cherny](https://borischerny.com/) -- the inventor of
[Claude Code](https://docs.anthropic.com/en/docs/claude-code) -- pioneered a practical workflow for
parallel agentic development: five git checkouts, each in its own tmux tab, each running Claude Code
in plan mode. This was one of the first demonstrations that a single developer could effectively
supervise multiple agents working on different tasks simultaneously, and it proved that the
bottleneck in agentic software engineering isn't the agent -- it's the coordination layer around it.

sase builds directly on this insight. Where Boris' method relies on the developer to manually manage
the parallelism -- switching between tmux tabs, keeping track of which checkout is doing what,
copy-pasting prompts, and mentally tracking the state of five concurrent workstreams -- sase
replaces that manual overhead with structured infrastructure:

- **Workspaces instead of manual checkouts** -- sase's workspace provider system creates and manages
  isolated working copies programmatically, eliminating the need to manually set up and maintain
  parallel git checkouts.
- **ChangeSpecs instead of mental bookkeeping** -- Each unit of work gets a tracked lifecycle with
  status, metadata, and history, replacing the cognitive load of remembering what's happening in
  each tmux tab.
- **XPrompts instead of ad-hoc prompts** -- Reusable, composable prompt templates with YAML front
  matter replace the prompt fragments scattered across shell history and scratch files.
- **True SDD instead of plan mode** -- Plan mode produces ephemeral plans that vanish when the
  session ends. sase persists committed prompts in the agents sidecar, ordinary tales and executable
  epics in the plans store, and exploratory notes in the `sdd/research/` corpus. For larger efforts,
  epic files carry a bead ID in their frontmatter that links them to an epic-tier bead, and each
  phase of the epic gets its own bead whose ID appears in the corresponding commit messages --
  creating a traceable chain from epic to phase to commit. For smaller tales, commit messages
  include a `SASE_PLAN=<path>` tag pointing back to the plan file. The result is spec-driven
  development where the full history of intent, decomposition, and execution is preserved and
  queryable, not trapped in a single agent session's context window.
- **ACE instead of tmux** -- A single TUI provides unified navigation, filtering, and management
  across all active workstreams, replacing the manual tab-switching workflow.
- **AXE instead of manual supervision** -- A background daemon handles scheduling, monitoring, and
  lifecycle management of agent runs, so the developer doesn't need to babysit each session.

The core idea -- that one developer can multiply their output by running several agents in parallel
-- was right. sase just replaces the duct tape with a proper framework.

## Beads

[Steve Yegge's](https://steve-yegge.medium.com/) [beads](https://github.com/steveyegge/beads) (`bd`)
introduced a critical insight: AI coding agents suffer from a "50 First Dates" problem -- every new
session starts from scratch with no memory of prior work. His solution was a dependency-aware graph
issue tracker designed specifically for agents, backed by [Dolt](https://github.com/dolthub/dolt) (a
version-controlled SQL database), with hash-based IDs for collision-free multi-agent writes,
hierarchical epics-to-subtasks via dotted IDs, atomic `--claim` operations for agent coordination,
and semantic memory compaction to keep the working set small. The key idea was that agents don't
need TODO files or markdown plans -- they need a structured, persistent memory layer they can query
and update across sessions, so that multi-session and multi-agent workflows stay coherent.

The `sase bead` command is a from-scratch reimplementation that carries this idea into sase's
architecture while drastically simplifying the surface area:

- **Rust-backed events plus compatibility mirrors instead of Dolt** -- sase stores canonical
  append-only events under `events/**`, generates sorted `issues.jsonl` for older tooling, and
  treats `beads.db` as a gitignored compatibility cache. Fresh clones read the tracked events
  directly and can rebuild both mirrors without an external database engine.
- **Plan tiers, executable phases, and standalone tasks** -- plan-like beads carry explicit `plan`
  or `epic` tiers, executable phases use hierarchical child IDs, delegated child epics can nest
  beneath phase/land work, and flat task beads capture independent follow-ups. Linked epics use
  `--type plan(<plan_file>) --tier epic`; epic approval creates the bead DAG deterministically and
  `sase bead work` launches one agent per phase plus a final land agent. The same command launches
  exactly one worker for a standalone task bead.
- **Checkout-local stores with normal VCS synchronization** -- `sase bead` reads and mutates the
  active checkout's canonical store rather than merging numbered sibling workspaces. In-tree bead
  state moves between checkouts through the normal VCS path; local and sidecar policies resolve
  their own documented store roots.
- **No external binary** -- beads ships as a ~37MB Go binary with its own daemon process;
  `sase bead` is installed as part of sase and uses the required `sase_core_rs` extension for local
  storage/query/mutation speed, with no separate daemon to run.

The philosophical debt is real: beads proved that giving agents structured issue tracking -- not
just chat history -- fundamentally changes what's possible in multi-session agentic workflows.
`sase bead` takes the ~5% of that system that matters for sase's orchestration model and integrates
it natively.

## Research Papers

This project was heavily influenced by two research papers:

- **[Agentic Software Engineering: Foundational Pillars and a Research Roadmap](https://arxiv.org/abs/2509.06216)**
  (Hassan et al., 2025) -- This paper's vision of Structured Agentic Software Engineering (SASE)
  inspired the project's name and overall direction. Its concepts of the Agent Command Environment
  (ACE) and Agent Execution Environment (AEE) directly informed the naming and design of the `ace`
  TUI and `axe` daemon, respectively.

  ![Visual overview of the SASE paper](images/sase_paper.png){ width="800" }

- **[PDL: A Declarative Prompt Programming Language](https://arxiv.org/abs/2410.19135)** (Vaziri et
  al., 2024) -- PDL's approach to declarative, YAML-based prompt programming influenced the design
  of xprompt workflows, sase's YAML-defined multi-step pipelines for orchestrating LLM calls and
  tool execution.

  ![Visual overview of the PDL paper](images/pdl_paper.png){ width="800" }

<sub>Images generated with [Nano Banana](https://notebooklm.google.com/) (Google's NotebookLM) via
Gemini.</sub>
