---
plan: sdd/tales/202606/agent_commit_messages_panel.md
---
 #fork:04j.f1 Great! Can you now help me add support for showing all of the commit messages associated with a given agent in the agent metadata panel on the "Agents" tab of the `sase ace` TUI? Currently, we only show the commit message from the main repo (not from linked repos). I want you to lead the design on this one. Make sure you design this feature so it is intuitive, reliable, and (last but not least) beautiful! Think this through thoroughly and create a plan using your `/sase_plan` skill. Submit your plan with the
`sase plan propose` command (as the skill instructs) before making any file changes.
 

%xprompts_enabled:false
### Questions and Answers

#### Q1: Sourcing

> How should we source each linked repo commit message for the metadata panel? The primary repo already persists meta_commit_message, and the SASE commit workflow has no linked-repo awareness today.

- [x] **Live-fetch off-thread (Recommended)** — Mirror the just-shipped linked-deltas feature: an off-thread worker resolves each repo workspace and asks the VCS provider for the agent commits (git log base..HEAD), cached in-memory for zero-I/O renders. No backend or runner changes; works retroactively for any agent whose workspaces still exist; degrades gracefully. Caveat: completed agents whose workspaces were recycled may show stale or no data.
- [ ] **Persist at commit time** — Extend the commit and finalize pipeline so every repo the agent commits records its message, symmetric with the primary meta_commit_message. Most reliable for completed agents and immune to workspace recycling, but larger scope (linked repos are not centrally committed today, so we add discovery and recording logic) and only covers agents run after the change.
- [ ] **Hybrid: persist plus live fallback** — Render persisted messages when present, fall back to live-fetch otherwise. Most robust coverage but the most complex to build and test.

#### Q2: Presentation

> How should the commit messages be presented in the metadata panel?

- [x] **Unified COMMITS section (Recommended)** — One new purpose-built COMMITS section grouping all repos (primary first, then each linked repo using the same glyph and accent styling as DELTAS). The primary message moves here, so we drop the generic Commit Message line from WORKFLOW VARIABLES to avoid duplication. Most beautiful and intuitive; all commit messages live in one place.
- [ ] **Additive (keep primary where it is)** — Leave the primary Commit Message line exactly where it is under WORKFLOW VARIABLES, and add a separate section for linked-repo commit messages only. Smaller change, but the primary and linked messages live in two different places.

#### Q3: Scope

> What scope of commits should each repo show?

- [x] **All of the agent commits on its branch (Recommended)** — List every commit on the agent working branch (git log base..HEAD) per repo. Honors all of the commit messages, matches the current multi-commit behavior (Commit Message 1, 2, ...), and naturally shows nothing when the agent made no commit (no stale or unrelated HEAD).
- [ ] **Only the latest commit per repo** — Show just the HEAD commit subject for each repo. Simpler and most compact, but loses earlier commits and may show an unrelated HEAD if the agent committed nothing in that repo.

%xprompts_enabled:true