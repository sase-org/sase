# SASE Rename Research - Consolidated

Date: 2026-06-22

This consolidates the two prior research notes:

- `sdd/research/202606/project_rename_naming_research_20260622.md`
- `sdd/research/202606/sase_rename_name_research.md`

## Question

What name would better fit the project currently called `sase`, reduce collision risk, and help a new user understand
the product before they learn the acronym expansion?

## Project Shape

The local README describes `sase` as a provider-neutral operating layer for coding agents. It does not replace Claude
Code, Codex, OpenCode, Qwen Code, or other provider CLIs. It coordinates them into tracked, repeatable engineering
workflows with isolated workspaces, reusable prompts, scheduling, status, review state, memory, artifacts, ChangeSpecs,
SDD/Beads, plugins, editor integration, and commit flow.

Naming implication: the replacement should cover durable, reviewable software-change coordination. Names that only say
"agent", "prompt", "chat", "kanban", or "worktree" understate the product.

## Why Rename

The current name has a hard public collision. In the security market, SASE means Secure Access Service Edge, pronounced
"sassy". Cisco describes it as a Gartner-coined 2019 category combining SD-WAN, secure web gateway, cloud access
security broker, firewall-as-a-service, and zero-trust network access. That is not a minor acronym overlap; it is a
mature enterprise-security category with large vendor and analyst gravity.

Consequences:

- Search terms like `sase`, `sase platform`, `sase docs`, and `sase orchestration` are structurally biased toward
  networking/security.
- The project shares both spelling and pronunciation with the security category.
- "Structured Agentic Software Engineering" is a useful descriptor, but the acronym is not ownable enough as a product
  name.

## Category Context

The coding-agent orchestration namespace is already crowded. The visible category language is converging around parallel
agents, git worktrees, tmux/sandbox isolation, task graphs, review loops, CI feedback, and human supervision. Augment's
2026 orchestrator roundup frames open-source agent orchestrators as tools for running multiple AI coding agents in
parallel across isolated git worktrees, with coordination depth as the key differentiator. Existing projects already use
or own obvious territory such as `agent-orchestrator`, `conductor`, `regatta`, `weft`, `tutti`, and `marl`.

Naming implication: the best territory is not "AI agents" in the abstract. It is controlled software change: specs,
workspaces, patches, diffs, review state, audit trail, and finalization.

## Verification and Corrections

Both prior files answered the original request and ended with five recommendations, but the stronger final result needs
several corrections:

| Prior candidate | Final handling |
| --- | --- |
| `Patchyard` | Strong semantics, but now an exact GitHub repo describes a local control room for Claude Code, Codex, Aider, Gemini CLI, and OpenCode in isolated git worktrees. Too adjacent to recommend. |
| `ChangePlane` | Clean registries, but exact GitHub repo hit describes AI-action governance. Too close for a clean rename. |
| `ChangeDeck` | Clean registries, but exact web/product hit as a Notion-connected public changelog tool. Demote. |
| `Corral` | Good CLI feel, but npm and crates.io exact packages exist; not clean enough if a broad ecosystem rename matters. |
| `Bosun` | npm exact package describes autonomous engineering and AI agent executors. Avoid. |
| `Coxswain` | PyPI/crates clean, but npm exact package exists and the spelling/binary split (`cox`) adds friction. |
| `Gantry` | Multiple package and product collisions. Avoid unless you deliberately want an infra-word with acquisition work. |
| `Muster` | Package collisions across PyPI/npm/crates; crates.io package is tmux-session related. Demote. |
| `PatchDock` | Existing molecular-docking tool named PatchDock. Avoid. |
| `SpecRail` / `SpecSlate` | Web/GitHub hits are directly adjacent to spec-driven agent workflows. Avoid. |

Registry and GitHub spot checks were rerun on 2026-06-22. For the final candidates below, exact PyPI, npm, and crates.io
queries returned `404`, and authenticated GitHub repository-name search returned zero exact repo-name hits. This is not
trademark clearance or a domain check.

## Naming Criteria

1. Short enough for a frequently typed CLI.
2. Clear spelling and pronunciation.
3. No dominant public meaning comparable to Secure Access Service Edge.
4. No known direct AI-agent, worktree, spec-orchestration, or dev-tool collision.
5. Broad enough for planning, workspace isolation, ChangeSpecs, memory, artifacts, review, and commit flow.
6. Works as a repo/package family: `<name>-core`, `<name>-github`, `<name>-nvim`.
7. Leaves room to keep "structured agentic software engineering" as a methodology descriptor under the new brand.

## Sources Checked

Local:

- `README.md`
- `pyproject.toml`
- `memory/sase.md`
- `memory/glossary.md`

External:

- [Cisco Umbrella: What is SASE?](https://umbrella.cisco.com/secure-access-service-edge-sase/what-is-sase)
- [Augment Code: 9 Open-Source Agent Orchestrators for AI Coding (2026)](https://www.augmentcode.com/tools/open-source-agent-orchestrators)
- [andyrewlee/awesome-agent-orchestrators](https://github.com/andyrewlee/awesome-agent-orchestrators)
- [AgentWrapper/agent-orchestrator](https://github.com/AgentWrapper/agent-orchestrator)
- [Addy Osmani: The Code Agent Orchestra](https://addyosmani.com/blog/code-agent-orchestra/)
- PyPI JSON API, npm registry, crates.io API, authenticated GitHub repository search, and exact-phrase web searches for
  leading and rejected candidates.

## Five Recommendations

1. **Specyard**

   Best overall recommendation. It is clean across the checked package registries and GitHub repo-name search, and it
   points at the part of SASE that most differentiates it from plain parallel-agent runners: durable specs, plans,
   ChangeSpecs, SDD artifacts, and controlled execution. `specyard run`, `specyard ace`, and `specyard doctor` are
   longer than `sase` but still readable. The tagline should make the agent angle explicit: "Specyard coordinates coding
   agents into reviewable software changes."

2. **PatchTower**

   Best if you want the brand to emphasize supervision and final code change. The tower metaphor fits scheduled runs,
   background agents, notifications, CI/review loops, and commit finalization. It cleared the spot checks and has a
   stronger command-center feel than `Specyard`. The main caveat is that "patch" can also suggest security patch
   management, so the first-line positioning should say "coding-agent patches" or "software changes" quickly.

3. **ChangeSlate**

   Best broad control-surface name. It covers planned, active, reviewed, and completed changes without overfitting to
   the final diff. "Slate" also fits the durable-record aspect: status, comments, mentors, artifacts, memory, and
   review state. It is less developer-native than `PatchTower` or `DiffYard`, but it is clean and flexible.

4. **DiffYard**

   Best short developer-native option. It is searchable, clear to engineers, and maps well to many isolated pieces of
   work waiting for review. It cleared the spot checks. The downside is scope: SASE does important work before a diff
   exists, including planning, scheduling, workspace allocation, memory reads, and artifact capture.

5. **PatchSlate**

   Best fallback if you like the `patch` vocabulary but want a quieter, more record-oriented name than `PatchTower`.
   It fits reviewable patches, state tracking, and commit flow while staying clean in the checked registries and GitHub
   search. It is less vivid than the top four, but it has low collision risk and a practical repo/package family:
   `patchslate-core`, `patchslate-github`, `patchslate-nvim`.
