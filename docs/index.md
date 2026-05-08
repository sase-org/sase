# Structured Agentic Software Engineering

SASE is a Python toolkit for dependable agent-driven software engineering. It provides the scheduling, tracking, and
workflow infrastructure around coding agents so repeated work can be planned, reviewed, resumed, and handed off without
losing context.

![Visual overview of SASE](images/sase_overview.jpg)

## What SASE Provides

- **ACE**: an interactive TUI for navigating ChangeSpecs, agents, notifications, and automation state.
- **AXE**: a background orchestration daemon for scheduled hooks, mentors, workflows, and maintenance jobs.
- **XPrompts**: reusable prompt templates and workflows with reference expansion, typed inputs, and provider routing.
- **ChangeSpecs**: tracked units of work with status, metadata, commits, review state, and VCS integration.
- **Beads**: git-native issue tracking for SDD plans, executable epics, dependencies, and multi-agent phase work.
- **Provider plugins**: shared abstractions for LLMs, version control, workspaces, notifications, and integrations.

## Start Here

- [ACE TUI User Guide](ace.md)
- [Spec-Driven Development](sdd.md)
- [XPrompt Template Reference](xprompt.md)
- [Workflow Specification](workflow_spec.md)
- [ChangeSpec Format](change_spec.md)
- [Bead Issue Tracking](beads.md)
- [Blog](blog/index.md)

## Why It Exists

Single agent runs are useful, but production engineering work needs more than a prompt and a terminal. SASE focuses on
the coordination layer: scheduling runs, preserving intent, tracking review state, supervising automation, and keeping
the workflow portable across agent providers.
