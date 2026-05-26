---
create_time: 2026-05-26
status: research
---

# Make `sase memory read` More Useful to SASE Agents

## Question

How should `sase memory read` evolve now that audited reads, write proposals, review, and log summaries exist? The
specific goal is agent usefulness: make it easier for an agent to discover, choose, read, and cite long-term memory
without weakening the audit and human-review boundaries.

## Short Answer

Yes, improve it. The current command is safe and auditable, but it is too literal for agents:

```bash
sase memory read long/generated_skills.md --reason "Need generated skill context"
```

That works only after the agent already knows the exact path. The next increment should make `read` an
agent-facing retrieval surface, not just a path-to-stdout helper.

Recommended v1 improvements:

```bash
sase memory read                         # show an agent-oriented readable catalog
sase memory read --json                  # machine-readable catalog
sase memory read --search "commit skill" # ranked readable memories, no content
sase memory read --for "editing generated commit skills" --json
sase memory read generated_skills -r "Need generated skill workflow before editing skill source"
sase memory read long/generated_skills.md -r "Need context" --json
sase memory read --dynamic               # show memory already injected for this agent, from artifacts when available
```

The highest-impact change is a catalog/search mode inside `read`, plus flexible path/name resolution and JSON read
receipts. Do not make agents write canonical memory, approve proposals, or silently read all long-term memory.

## Current Local State

The current memory command group has:

- `sase memory init`
- `sase memory list`
- `sase memory read`
- `sase memory write`
- `sase memory review`
- `sase memory log`

Relevant implementation:

- `src/sase/main/parser_memory.py` registers `read` with a required `memory-relative-path` and required `--reason`.
- `src/sase/memory/cli_read.py` validates, reads, logs, and prints content.
- `src/sase/memory/read_log.py` validates only `memory/long/*.md`, rejects `memory/short`, strips leading YAML
  frontmatter, requires agent attribution, and appends project-scoped JSONL under `~/.sase/projects/<project>/`.
- `src/sase/memory/cli_log.py` summarizes read counts and can include proposal/review audit events.
- `src/sase/xprompts/skills/sase_memory_read.md` tells agents to use the command when long-term memory is required.
- `docs/memory.md` documents the audited read contract and says normal human shells should start with list/log/review.

The command is intentionally safe:

- It refuses reads without `SASE_AGENT_NAME`, `SASE_AGENT`, or `SASE_ARTIFACTS_DIR/agent_meta.json`.
- It does not read `memory/short`.
- It does not log file contents.
- It strips frontmatter from stdout but records metadata in the audit event.

The problem is discoverability:

- `sase memory read --help` gives only a path example. It does not show how an agent should find the right memory file.
- `sase memory list` is human-readable only and does not expose descriptions, keywords, dynamic eligibility, or prior
  read stats as structured data.
- `sase xprompt list` can show memory xprompts, but it omits the `keywords` frontmatter and currently showed
  `description: null` for `memory/long/generated_skills`.
- `sase memory list` currently reports a spurious missing reference for `memory/long/*.md` because `AGENTS.md` mentions
  the glob pattern in prose and the inventory parser treats it like a concrete path.
- In this checkout, `sase memory list` reports 2 referenced long-term memories:
  - `memory/long/generated_skills.md`
  - `memory/long/tui_jk_baseline.md`
- Only `generated_skills.md` has `keywords` frontmatter, so it is the only dynamic long-memory source visible via the
  xprompt catalog. `tui_jk_baseline.md` has a description but no keywords, so agents must intentionally read it.
- `sase memory log --json` currently shows reads only for `long/generated_skills.md`, which suggests either low use,
  low need, or low discoverability. Given the command is new and path-exact, discoverability is the likely bottleneck.

There is also an already-approved direction for surfacing reads in ACE:

- `sdd/tales/202605/memory_reads_in_agent_panel.md` proposes a MEMORY READS section in the Agents tab detail panel.
- That makes read events visible after they happen, but it does not help agents pick the correct memory before reading.

## External Signals

Claude Code's `/memory` command is explicitly an inspection and debugging surface: it lists loaded memory files,
supports opening/editing memory files, and its troubleshooting docs tell users to run `/memory` to verify that relevant
files were loaded. Claude also now uses a concise `MEMORY.md` index plus topic files read on demand, and documents that
only the first 200 lines or 25KB of `MEMORY.md` load at startup.

Letta Code MemFS uses a git-backed markdown memory tree. Two details map directly to SASE:

- Each memory file has required `description` frontmatter that is visible to the agent even when the full file is not
  loaded.
- The CLI includes operational commands such as `status`, `diff`, `backup`, `restore`, `export`, and `tokens`; `tokens`
  is specifically for spotting always-loaded memory bloat.

OpenHands separates always-on `AGENTS.md` context from on-demand skills. Its AgentSkills format keeps only descriptions
in the available-skills list and lets the agent invoke full content when needed. This reinforces the SASE split between
short memory, dynamic memory, and audited long-memory reads.

Recent memory-poisoning research argues against relaxing write boundaries. Papers in 2026 show that persistent memory
can become a cross-session attack surface when untrusted content is stored and later treated as instruction. That means
`sase memory read` should become better at read-only discovery and provenance, while `write` and `review` should remain
the only path into canonical long-term memory.

## Recommendation

### 1. Make `sase memory read` without a path show a readable catalog

Agents need a first move when they see instructions like "use `/sase_memory_read` for relevant long-term memory." A bare
`sase memory read` should be that first move.

Suggested text output:

```text
Readable long-term memory for project sase

path                         dynamic  reads  description
long/generated_skills.md     yes      5      Skill file generation pipeline, CLI/skill contract synchronization, commit skills per runtime.
long/tui_jk_baseline.md      no       0      Baseline j/k key-to-paint latency data and reproduction steps.

Use: sase memory read <path-or-name> --reason "specific reason"
```

Suggested JSON shape:

```json
{
  "project": "sase",
  "readable": [
    {
      "canonical_path": "long/generated_skills.md",
      "name": "memory/long/generated_skills",
      "slug": "generated_skills",
      "source_path": "memory/long/generated_skills.md",
      "description": "Skill file generation pipeline, CLI/skill contract synchronization, commit skills per runtime.",
      "keywords": ["sase commit", "SKILL.md", "commit skill"],
      "dynamic": true,
      "inventory_status": "referenced",
      "read_count": 5,
      "last_read_at": "2026-05-24T21:26:34.939393+00:00"
    }
  ]
}
```

Why put this under `read` instead of only `list`:

- The agent skill points at `sase memory read`, so the discovery affordance should be reachable from that command.
- `list` is a launch-context dashboard. `read` should be the audited long-memory doorway.
- A catalog mode does not mutate state or create an audit event, so it is safe as a default when no path is provided.

### 2. Add `--search` and `--for` for path selection

Agents often know the task, not the memory filename. Add a lightweight ranking mode:

```bash
sase memory read --search "commit skill"
sase memory read --for "I am editing src/sase/xprompts/skills/sase_memory_read.md"
```

Initial ranking can stay simple and deterministic:

- match query tokens against slug, stem, title/heading, `description`, `keywords`, and AGENTS Tier 3 prose;
- prefer exact keyword/slug hits over body hits;
- show why a memory matched;
- do not print full memory content unless a path is supplied.

This is not semantic search yet. It is a deterministic selector that helps agents choose a path and write a specific
reason.

Example:

```text
2 candidate memories

1. long/generated_skills.md
   why: keyword "SKILL.md", description contains "skill"
   read: sase memory read long/generated_skills.md --reason "Need generated skill workflow before editing skill sources"

2. long/tui_jk_baseline.md
   why: no query match; referenced long-term memory
```

### 3. Accept more natural memory identifiers

Keep the canonical audit path as `long/<slug>.md`, but allow common aliases at the CLI boundary:

- `generated_skills`
- `long/generated_skills`
- `long/generated_skills.md`
- `memory/long/generated_skills.md`
- `memory/long/generated_skills`
- `memory/long/generated_skills` xprompt-style name
- `.sase/memory/long-generated-skills.md` when it can be mapped back to a canonical long memory

The audit event should still record:

- `canonical_path: "long/generated_skills.md"`
- `requested_path: "generated_skills"` or equivalent new field
- `resolved_path`

This preserves stable logs while removing unnecessary friction for agents.

### 4. Add `--json` to successful reads

Plain stdout body is good for direct context injection, but agents and tools need a receipt.

Suggested:

```bash
sase memory read generated_skills -r "Need generated skill workflow" --json
```

Output:

```json
{
  "event": {
    "id": "read-a1b2c3d4e5f6",
    "timestamp": "2026-05-26T00:00:00+00:00",
    "canonical_path": "long/generated_skills.md",
    "agent_name": "agent-a",
    "reason": "Need generated skill workflow",
    "frontmatter_stripped": true,
    "byte_count": 2031
  },
  "content": "# Generated Skill Files\n..."
}
```

Also print a read receipt to stderr in non-JSON mode:

```text
sase memory read: logged read-a1b2c3d4e5f6 for long/generated_skills.md
```

Keep the body on stdout so existing command substitution and agent usage do not break.

### 5. Add `--dynamic` to show what this agent already received

Dynamic memory is currently visible in launch output and in `dynamic_memory.json`, but agents do not have an easy
runtime query.

When `SASE_ARTIFACTS_DIR/dynamic_memory.json` exists:

```bash
sase memory read --dynamic
```

Should show:

- matched memory names;
- matched keywords;
- dynamic file path, such as `.sase/memory/long-generated-skills.md`;
- source canonical path when known;
- whether the dynamic file is still present;
- guidance that a fresh audited read is unnecessary if the dynamic file is already attached and current.

This mode should not create a read event. It is introspection of already-injected context.

### 6. Surface dynamic eligibility and keywords in the catalog

The catalog should answer:

- Is this long-term memory dynamically matchable?
- Which keywords trigger it?
- Which long-term memories have descriptions but no keywords?
- Which dynamically matchable files are never referenced from AGENTS Tier 3?

This matters because `tui_jk_baseline.md` is referenced and described but not dynamic. That might be intentional, but an
agent has no way to know from `read --help`.

### 7. Fix inventory false positives before relying on catalog output

`sase memory list` currently treats the prose token `memory/long/*.md` as a missing file. For agent-facing discovery,
that kind of noise is harmful.

Fix `_MEMORY_PATH_RE` or post-parse validation so tokens containing glob metacharacters (`*`, `?`, `[`) are either
ignored or reported separately as patterns, not missing concrete files. This is not a `read` feature, but the catalog
should share inventory logic and should not inherit this false positive.

### 8. Defer semantic/vector search until deterministic search is proven insufficient

There is a tempting larger feature:

```bash
sase memory search "how do generated codex skills work?"
```

That may be useful later, especially if the long-memory pool grows. It should not block the next `read` improvement.
Deterministic search over slug, description, keywords, and headings is enough for the current memory shape, easier to
test, and safer for auditability.

## Proposed Command Contract

Path read:

```bash
sase memory read <path-or-name> --reason <reason> [--json]
```

Catalog:

```bash
sase memory read [--json]
```

Selection:

```bash
sase memory read --search <query> [--json]
sase memory read --for <task-description> [--json]
```

Runtime introspection:

```bash
sase memory read --dynamic [--json]
```

Validation:

- `--reason` is required only when content is actually read and audited.
- Catalog/search/dynamic modes must not append read-log events.
- Content reads still require agent attribution.
- Catalog/search can run in a human shell; if there is no agent identity, include a note that content reads will require
  attribution.
- Never read `memory/short`.
- Never approve or mutate canonical memory from `read`.

## Implementation Sketch

Add a reusable catalog builder, probably `src/sase/memory/catalog.py`, that joins:

- inventory entries from `build_memory_inventory()`;
- long-memory frontmatter (`description`, `keywords`);
- dynamic xprompt data from `loader_memory.py`;
- read stats from `read_memory_read_events()`;
- AGENTS Tier 3 descriptions where frontmatter is absent or stale.

Then update:

- `parser_memory.py`: make `memory_path` optional; add `--json`, `--search`, `--for`, `--dynamic`.
- `cli_read.py`: dispatch catalog/search/dynamic modes before requiring `--reason` or agent identity.
- `read_log.py`: add alias normalization and, optionally, `requested_path` to schema v2 events.
- `cli_list.py`: either reuse the catalog or at least align status/dynamic metadata.
- tests:
  - catalog includes descriptions, keywords, dynamic flag, inventory status, and read stats;
  - bare `read` does not log;
  - `--search` ranks exact slug/keyword matches;
  - path aliases canonicalize to the same audit path;
  - `--json` read includes content plus event receipt;
  - `--dynamic` reads `dynamic_memory.json` without logging;
  - glob-like prose tokens do not become missing files.

If Rust core is meant to own cross-frontend catalog behavior later, define the JSON schema as the stable wire shape now.
Python can implement it first, but the shape should be suitable for `sase-core` once memory catalog data matters to ACE,
mobile, or editor integrations.

## What Not To Do

- Do not make `read` auto-read every referenced long-term memory. That recreates the always-loaded context bloat the
  tiered memory design avoids.
- Do not make `read` propose, edit, or approve memory. Keep `write` and `review` as the explicit authoring boundary.
- Do not hide audit logging behind search. Search/catalog/dynamic introspection are not reads; content access is.
- Do not rely only on dynamic memory matching. Dynamic matching is helpful, but it is prompt-keyword based and can miss
  relevant memory. Agents still need a deterministic manual read path.
- Do not require humans to fake agent identity for catalog/search. Humans should be able to inspect the catalog without
  creating audit events.

## Ranking

1. Bare `sase memory read` catalog with `--json`.
2. `--search` / `--for` deterministic selector.
3. Alias normalization for path/name inputs.
4. `--json` content reads with event receipt and stderr receipt for non-JSON.
5. `--dynamic` agent runtime introspection.
6. Inventory false-positive fix for glob-like prose paths.
7. Token estimates and bloat warnings in the catalog.
8. Later: semantic search and cross-memory retrieval.

## Sources

Local:

- `src/sase/main/parser_memory.py`
- `src/sase/memory/cli_read.py`
- `src/sase/memory/read_log.py`
- `src/sase/memory/cli_list.py`
- `src/sase/memory/inventory.py`
- `src/sase/memory/dynamic.py`
- `src/sase/xprompt/loader_memory.py`
- `src/sase/xprompts/skills/sase_memory_read.md`
- `docs/memory.md`
- `sdd/epics/202605/memory_read_log.md`
- `sdd/tales/202605/memory_reads_in_agent_panel.md`
- `sdd/research/202605/sase_memory_command_research.md`
- `sdd/research/202605/sase_memory_command_subcommands.md`

External:

- Claude Code memory docs: https://code.claude.com/docs/en/memory
- Letta Code MemFS docs: https://docs.letta.com/letta-code/memfs/
- OpenHands skills overview: https://docs.openhands.dev/overview/skills
- OpenHands Agent Skills guide: https://docs.openhands.dev/sdk/guides/skill
- "Poison Once, Exploit Forever" arXiv: https://arxiv.org/abs/2604.02623
- "Zombie Agents" arXiv: https://arxiv.org/abs/2602.15654
- "Memory Poisoning Attack and Defense on Memory Based LLM-Agents": https://huggingface.co/papers/2601.05504
