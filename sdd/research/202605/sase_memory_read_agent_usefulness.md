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

Anthropic's context-engineering guidance points in the same direction from a different angle: keep cheap identifiers
such as file paths, queries, and links in context, then load detailed content just in time with tools. Basic Memory and
Goose also treat runtime memory retrieval as a first-class command/tool surface, and both reinforce the value of clean
CLI output plus structured machine-readable modes. The AGENTS.md evaluation paper is a useful caution here: repository
instruction files can increase cost or reduce success when they add irrelevant context, so SASE should prefer precise
on-demand reads over adding more always-loaded long-term memory.

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

### 9. Add progressive read modes before full retrieval becomes the only option

The catalog/search path helps agents choose a memory. Once they choose one, the next useful improvement is progressive
disclosure inside the audited read flow:

```bash
sase memory read long/generated_skills.md --metadata -r "Check whether this is relevant"
sase memory read long/generated_skills.md --toc -r "Find the relevant section"
sase memory read long/generated_skills.md --section "CLI/Skill Contract Synchronization" -r "Need CLI contract details"
sase memory read long/generated_skills.md --grep "init-skills" --context 3 -r "Locate regeneration command"
```

These modes should still create read-log events, because they expose memory content or content-derived structure. They
should record `output_mode`, `start_line`, `end_line`, and omitted-line counts so later audit analysis can distinguish a
full read from a metadata, table-of-contents, section, or grep read.

Implementation can stay deterministic:

- parse YAML frontmatter with the same helper used for full reads;
- parse Markdown ATX headings for `--toc` and `--section`;
- match sections by exact heading first, then slug;
- keep `--grep` literal by default, with explicit case/context flags if needed.

### 10. Make read receipts content-version aware

JSON reads should be more than "body plus event id." They should let a later person answer exactly what an agent saw
without logging the memory body itself.

Add schema-v2 event fields such as:

- `requested_path`
- `canonical_path`
- `raw_sha256`
- `body_sha256`
- `line_count`
- `approx_token_count`
- `output_mode`
- `start_line`
- `end_line`
- `omitted_line_count`
- `git_commit` or `git_tree` when available

Keep schema-v1 log readers tolerant. The hashes and ranges are enough to prove the content version later while
preserving the current "metadata, not content" audit boundary.

### 11. Surface dynamic-memory state without hiding output

When `SASE_ARTIFACTS_DIR/dynamic_memory.json` exists, `--json`, `--metadata`, and `--dynamic` should report whether the
requested canonical memory was already injected into the current agent launch. Useful fields include matched keywords,
source memory name, dynamic artifact path, generated `.sase/memory` path, and whether the dynamic file is still present.

Do not make a normal content read silently skip stdout just because the memory was already loaded dynamically. That
would be surprising in shell pipelines. If skipping is useful later, make it explicit, for example
`--metadata --if-loaded`.

## Proposed Command Contract

Path read:

```bash
sase memory read <path-or-name> --reason <reason> [--json]
```

Progressive read:

```bash
sase memory read <path-or-name> --metadata --reason <reason> [--json]
sase memory read <path-or-name> --toc --reason <reason> [--json]
sase memory read <path-or-name> --section <heading-or-slug> --reason <reason> [--json]
sase memory read <path-or-name> --grep <literal> [--context N] --reason <reason> [--json]
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

- `parser_memory.py`: make `memory_path` optional; add `--json`, `--search`, `--for`, `--dynamic`, `--metadata`,
  `--toc`, `--section`, `--grep`, and `--context`.
- `cli_read.py`: dispatch catalog/search/dynamic modes before requiring `--reason` or agent identity.
- `read_log.py`: add alias normalization plus `requested_path`, content hashes, output mode, and output range to schema
  v2 events.
- `cli_list.py`: either reuse the catalog or at least align status/dynamic metadata.
- tests:
  - catalog includes descriptions, keywords, dynamic flag, inventory status, and read stats;
  - bare `read` does not log;
  - `--search` ranks exact slug/keyword matches;
  - path aliases canonicalize to the same audit path;
  - `--json` read includes content plus event receipt;
  - metadata, toc, section, and grep reads log the right mode/range without logging body content;
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
- Do not add automatic LLM summarization to `read`. It adds cost, nondeterminism, and another prompt-injection surface.
- Do not make semantic search a side effect of a content read. If SASE needs semantic retrieval later, give it its own
  command and evaluation story.

## Ranking

1. Bare `sase memory read` catalog with `--json`.
2. `--search` / `--for` deterministic selector.
3. Alias normalization for path/name inputs.
4. `--json` content reads with event receipt and stderr receipt for non-JSON.
5. Metadata and table-of-contents reads.
6. Section and grep reads with audited output ranges.
7. Content hashes, token estimates, and line counts in schema-v2 read events.
8. `--dynamic` agent runtime introspection.
9. Inventory false-positive fix for glob-like prose paths.
10. Token estimates and bloat warnings in the catalog.
11. Later: semantic search and cross-memory retrieval.

## Gaps and Additional Observations

These are constraints and details that should shape the recommendations above but were not surfaced in the previous
pass.

### A. Short-option convention is mandatory

`memory/short/gotchas.md` requires every `sase` command-line option to have both a long and short form
(`-f|--foobar`, not just `--foobar`). The recommendations introduce `--search`, `--for`, `--json`, `--dynamic` with no
short forms. That is a blocker by project policy. Concrete proposal, picked to avoid collisions with the existing
`-r/--reason`:

- `-s, --search`
- `-F, --for` (capital `F` so it does not clash with a future `-f` shorthand for filtering, and so it never collides
  with a `-r` reason swap)
- `-j, --json`
- `-d, --dynamic`
- `-m, --metadata`
- `-t, --toc`
- `-S, --section`
- `-g, --grep`
- `-c, --context`

Note that `-r` is already taken by `--reason`. A path-listing `--paths-only` toggle (often useful for scripts) would
need its own short form; `-p` is a safe default.

### B. Read-log schema is v1 and has no `requested_path` field

`src/sase/memory/read_log.py` defines `READ_LOG_SCHEMA_VERSION = 1` and `MemoryReadEvent` with these exact fields:
`schema_version, id, timestamp, project, cwd, canonical_path, resolved_path, agent_name, agent_source, artifacts_dir,
reason, byte_count, frontmatter_stripped`. `agent_source` is a `Literal["SASE_AGENT_NAME", "SASE_AGENT", "agent_meta"]`.

The alias-normalization recommendation needs a `requested_path` field so that audit logs show what the agent asked for,
not just what was resolved. That is a schema v2 change. Bump the constant, write events with `schema_version: 2`, and
keep readers (catalog, ACE, `memory log`) tolerant of both versions.

### C. ACE TUI already consumes the read log

`src/sase/ace/tui/memory_reads.py` and `src/sase/ace/tui/widgets/prompt_panel/_agent_memory_reads.py` already load and
display `MemoryReadEvent` rows in the Agents tab. Any schema change touches them directly. Two implications:

- Any new optional field (`requested_path`, `via`, `received_aliases`) must default safely when missing, because old
  log files will still be on disk.
- The catalog JSON shape proposed under recommendation 1 is a likely future consumer too. Define one canonical JSON
  schema and reuse it from both `read --json` and any future ACE catalog panel, rather than letting each surface invent
  its own.

### D. The skill file already does some of the work — but not all

`src/sase/xprompts/skills/sase_memory_read.md` already tells agents to prefer dynamic `.sase/memory/long-*.md` files
when they are attached, and not to re-read the canonical file unless a fresh audited read is required. That partly
covers recommendation 5 (`--dynamic`) from the policy side. What is missing from the skill is:

- A first move when no dynamic memory is attached and the agent does not know which file to choose. Today the skill
  says "read with a specific reason" but does not point at any discovery surface.
- A statement that repeat reads of the same memory in one agent session are wasteful (the audit event is recorded each
  time; the log will grow). The catalog mode can report `read_count` per agent for the current run, which would let an
  agent self-throttle.

When recommendation 1 lands, the skill should be updated in the same change to point at `sase memory read` (no args)
and `sase memory read --search <query>` as the discovery move.

### E. Dynamic memory keyword matching is word-boundary regex, not substring

`src/sase/memory/dynamic.py` builds case-insensitive regex patterns with `\b` anchors at word-character edges and
supports `!`-prefixed negative keywords that mask spans before positive matching. Two consequences for the catalog and
`--search` design:

- The catalog should display keywords exactly as authored, including `!`-prefixed exclusions, so agents understand why
  a memory did or did not dynamically match.
- The `--search` ranker should use the same matching semantics as dynamic memory, not a different tokenizer. Otherwise
  agents will see a memory in `--search` results that never dynamically matches their actual prompt, or vice versa,
  which is confusing.

Dynamic file paths are slug-mangled to `.sase/memory/long-<slug>.md` (underscores in slug preserved, slashes replaced
with hyphens at the layer above). Alias normalization in recommendation 3 must round-trip through this transform
correctly, including when the dynamic file is stale and no longer matches the canonical source.

### F. Approximate-token accounting already exists

`src/sase/memory/inventory.py` includes an `approx_token_count` field used by `sase memory list`. The Letta-style
`tokens` capability is partially built. The catalog under recommendation 1 should reuse `approx_token_count` rather
than reinventing a separate estimator, and the JSON shape should include it:

```json
{
  "canonical_path": "long/generated_skills.md",
  "approx_token_count": 612,
  "...": "..."
}
```

Add a clear warning band (for example: warn at >2k tokens, suggest splitting at >5k) only after at least one long
memory file actually crosses those thresholds. Today the existing files are small enough that warnings would be noise.

### G. Proposal ledger is read-aware-able

`src/sase/memory/proposals/ledger.py` tracks pending memory write proposals. `sase memory read` has no awareness of
this today. A low-risk enhancement: when the catalog or a content read covers a path that has a pending proposal, emit
a non-fatal note such as:

```text
sase memory read: long/generated_skills.md has 1 pending proposal (id <proposal-id>). Use `sase memory review` to view.
```

This does not leak proposed content (the agent still cannot read the proposal body without going through `review`),
but it warns the agent that what they just read may already be considered out of date by someone else.

### H. Error paths collapse to exit code 1

`src/sase/memory/cli_read.py` exits with `sys.exit(1)` for every failure: missing file, traversal, `memory/short`
rejection, missing reason, missing agent identity. Agents cannot distinguish a recoverable mistake (typo in path) from
a hard policy refusal (`memory/short` is never readable). For agent usefulness, consider:

- Stable error tags in stderr (`error: NO_AGENT_IDENTITY`, `error: PATH_NOT_ALLOWED`, `error: PATH_NOT_FOUND`) without
  changing exit codes. This is cheaper than a structured exit-code scheme and is enough for agents to retry sensibly.
- `--json` on failure should also return an error envelope with the same tag, so JSON-using agents do not have to
  parse stderr.

### I. Catalog/list overlap is real; pick one canonical surface

`sase memory list` already renders a per-file dashboard with description and approx-token columns. Recommendation 1
adds another surface for similar data. To avoid drift:

- Extract one catalog builder (recommendation 1's `src/sase/memory/catalog.py`) and call it from both `list` and
  `read`-no-arg.
- Pick one canonical JSON shape and use it for `list --json`, `read --json` (no args), and ACE consumption. Different
  shapes per command will produce subtle bugs.

### J. Tests pin exact error strings

`tests/test_memory_read_log.py` matches error messages with `pytest.raises(..., match=...)`. Any rewording of errors,
including the addition of stable error tags in recommendation H, will require updating those tests in the same change.
This is small but easy to forget and will block CI if missed.

### K. Reason quality is only whitespace-validated today

`normalize_read_reason` in `src/sase/memory/read_log.py` strips and rejects empty strings, nothing more. An agent can
pass `--reason "x"` or `--reason "context"` and the read will succeed and audit cleanly. That weakens the audit value of
the `reason` field, which is the only human-facing handle on *why* an agent saw the content.

Cheap, deterministic floors worth considering (do them at the same time as recommendation H so error tags exist):

- Minimum normalized length (for example, 12 characters or 3 words).
- Reject reasons that are pure stopwords or single tokens.
- Reject reasons that exactly match the canonical path or basename (a common agent shortcut).
- Optional `--reason-from-file` for long structured reasons, so the floor does not push agents toward shell-escaping
  multi-line strings.

Do not add LLM-based reason scoring. That re-introduces nondeterminism and a prompt-injection surface into the audit
boundary the command is supposed to protect.

### L. The read log is host-local and not VCS-tracked

`memory_read_log_path()` writes to `~/.sase/projects/<project>/memory_reads.jsonl`. That path is outside the repo and
outside any sibling repo. Implications the prior pass did not call out:

- Two machines reading the same canonical memory will produce two disjoint log files. `sase memory log` only sees the
  local one. Any catalog `read_count` is also local-only.
- A user reviewing an agent's behavior from a different machine cannot see the audit unless logs are synced separately.
- The log survives ephemeral `sase_<N>` workspace deletion (good), but tying a row back to the workspace that produced
  it depends on the `cwd` field staying meaningful (see L below).
- Anything that proposes ACE-side display of read counts (the catalog, the existing `_agent_memory_reads.py` panel)
  must be honest that "reads" means "reads visible to this host."

A small near-term fix: when emitting catalog or `--json` output, include a `log_scope: "host_local"` field so downstream
consumers do not assume global counts. A bigger optional step: support a configurable shared log location (NFS, S3, or
the existing multi-machine sync mechanism), gated behind a config key. Do not enable shared logs by default; concurrent
appends to a non-POSIX-locked file system would silently corrupt JSONL.

### M. The event `cwd` records the ephemeral workspace, not a stable repo identity

`build_memory_read_event` sets `cwd=str((cwd or Path.cwd()).resolve(strict=False))`. In a SASE workspace, that resolves
to `/home/.../sase_15`, `/home/.../sase_16`, and so on across runs. Cross-workspace analysis ("how many times has any
agent read this memory in the sase project?") has to strip the trailing `_<N>` to aggregate.

Recommendation: in schema v2, add a `workspace` block, for example:

```json
{
  "workspace": {
    "path": "/home/bryan/.local/state/sase/workspaces/sase-org/sase/sase_15",
    "number": 15,
    "project_root": "/home/bryan/.local/state/sase/workspaces/sase-org/sase/sase_15",
    "logical_repo": "sase-org/sase"
  }
}
```

Keep the existing `cwd` for back-compat. The `logical_repo` slot lets cross-workspace analytics use the same key as the
project memory name. This composes with recommendation L: even host-local logs become usable across many ephemeral
checkouts.

### N. The schema-v1 reader hard-rejects future events; v2 cannot ship until it is loosened

`_event_from_mapping` at `src/sase/memory/read_log.py:434` short-circuits with
`if data.get("schema_version") != READ_LOG_SCHEMA_VERSION: return None`. Today that is "tolerate corrupted rows." After
a v2 bump it becomes "silently drop every v2 event you wrote yesterday." Any v1→v2 migration must:

1. Land a tolerant reader first that accepts `schema_version in {1, 2}` and back-fills missing v1-only fields with
   safe defaults.
2. Wait one release cycle so old binaries upgrade before any writer starts emitting v2.
3. Only then bump `READ_LOG_SCHEMA_VERSION` and start writing v2.

`sase memory log`, the ACE TUI consumers in `_agent_memory_reads.py`, and the catalog all sit downstream of this
reader. Bump them as one change set, with tests covering "mixed v1+v2 file" explicitly.

### O. Concurrent reads serialize on a single exclusive lock

`append_memory_read_event` takes `fcntl.LOCK_EX` on a sibling `.lock` file for every append. Many concurrent agents will
serialize on that lock. At today's volume (single-digit reads per agent per day) this is invisible. Two things to keep
in mind as the catalog and progressive-read modes land:

- The catalog and any future "self" read-log views call `read_memory_read_events`, which takes `LOCK_SH`. That blocks
  appends until the read completes, so a `--json` catalog over a large log file briefly stalls concurrent reads. Use
  bounded summary loading (cap rows, cap age) rather than always re-reading the full file.
- Progressive-read modes still create one event per call. A `--toc` followed by `--section` followed by `--lines` is
  three appends. That is fine for audit, but `read_count`-based ranking in the catalog will inflate. Consider counting
  *full-body equivalent* reads separately from partial reads when ranking.

### P. CLI is one surface; MCP and SDK consumers want the same primitive

The current command assumes the agent runtime can shell out and parse stdout/stderr. Some runtimes prefer MCP tools or
in-process SDK calls and do not shell well (long stdout, escaping, ANSI). Three actions keep the audit boundary uniform
across surfaces:

- Expose a stable Python entry point, for example `sase.memory.read_api.read_memory(path, reason, *, mode, identity)`,
  that the CLI handler in `cli_read.py` becomes a thin wrapper over. Hooks, future MCP servers, and ACE all call the
  same function and write the same event.
- When `sase-core` later owns cross-frontend memory APIs, the Rust binding should expose the same shape.
- If/when an MCP server is added, prefer one tool per mode (`memory.read.full`, `memory.read.metadata`,
  `memory.read.section`, `memory.search`, `memory.catalog`) over one mega-tool. Tool descriptions are how MCP-driven
  agents discover affordances; a single overloaded tool hides the progressive modes the same way the current
  path-only CLI hides discovery.

This is not a near-term shipping item, but the JSON shapes in recommendations 1 and 4 should be designed assuming an
MCP wrapper will exist later.

### Q. `--lines N-M` is the missing composition primitive after `--grep`

Recommendation 9 covers `--metadata`, `--toc`, `--section`, and `--grep --context`. The natural next move after `--grep`
finds a hit on line 142 is "read lines 130–160 with full audit." Today's options force the agent to either re-grep with
larger context (loses precision) or read the whole file (loses the partial-read benefit).

Add `--lines <start>-<end>` (and `-L` as the short form) to the progressive set. Event fields already cover this:
`output_mode: "lines"`, `start_line`, `end_line`, `omitted_line_count = total_lines - (end - start + 1)`. Cap the
range at, for example, 1000 lines so this does not become a stealth full read.

This composes cleanly with `--json`: `--grep` returns matching line numbers in the event, and a follow-up `--lines`
read can cite those numbers as the reason (`--reason "follow-up on grep hit at line 142"`).

### R. Memory-read events are a natural hook trigger

The repo has a hooks system but no documented integration with memory reads. Possible hooks that would not weaken the
audit boundary:

- `on_memory_read`: fires after `append_memory_read_event`. Useful for: notifying a reviewer when sensitive long memory
  is touched; updating a per-agent context bar in ACE without polling the log; warning the agent itself via stderr
  when the read is the third+ read of the same path in the same session.
- `before_memory_read`: pre-flight veto for policy enforcement (for example: block reads from agents in a constrained
  family). This must run synchronously and must default to allow on hook error so a broken hook does not block all
  reads.

Hooks deserve their own design pass and should not block recommendations 1–4. Worth listing now so the schema-v2 event
shape leaves room for a `hook_decisions` array.

### S. Reads and citations are different events; the schema only models reads

`MemoryReadEvent` records what the agent *saw*. It does not record what the agent *used* in its eventual output, nor
which memory the agent claimed informed a write proposal. That gap matters because:

- Reviewing a write proposal benefits from knowing which long memories the proposing agent read first.
- An agent that read 5 memories but only cited 1 looks the same in the log as one that cited all 5.
- Auditing memory-poisoning incidents (see prior research's external sources) needs to follow the read → output edge,
  not just the read edge.

Do not graft citation into `MemoryReadEvent`. Add a separate event type (for example `MemoryCitationEvent`) that
references read event IDs and the artifact or proposal that cites them, and surface it through the same `memory log`
command. This pairs naturally with the proposal ledger in recommendation G.

### T. Content hashes must hash what the agent saw, not the raw file

Recommendation 10 lists both `raw_sha256` and `body_sha256`. Worth being precise about what each covers, because the
frontmatter strip and the progressive-read modes change the boundary:

- `raw_sha256`: SHA-256 of the file as it lives on disk, before any strip or slice. Stable per file version.
- `body_sha256`: SHA-256 of *the exact bytes returned on stdout for this read*. After frontmatter strip for full
  reads. After heading-bounded slicing for `--section`. After line slicing for `--lines`. After grep filtering for
  `--grep`.
- For `--metadata` and `--toc`, the body hash should cover the structured output bytes (canonicalized JSON if `--json`,
  the human-readable text otherwise). Document the canonicalization, or the hash is not reproducible.

Without this discipline, a later auditor cannot tell whether the agent saw the value at line 142 or a different value
at line 142 from a different file version. The hash becomes "trust me, it was something."

## Open Questions

- Should `sase memory read` ever return content from a dynamic file when the canonical file is unreadable for some
  reason (permissions, IO error)? Today the answer is "no, fail." That is probably still right, but worth confirming
  before recommendation 5 ships.
- Should the catalog include AGENTS Tier 3 entries that have no canonical file on disk yet? Right now they would show
  as missing under inventory; a catalog-friendly state might be `inventory_status: "declared_only"`.
- Should `--search` be available without agent identity (so humans can drive it from a shell)? The recommendations
  imply yes; confirm and lock in tests.
- Should `--reason` enforce a minimum quality floor (recommendation K), and if so, what is the right floor before it
  starts pushing agents toward boilerplate ("read for context before editing the file") that defeats the audit value?
- Should the read log live host-locally forever (recommendation L), or is there a SASE-wide place for cross-host audit
  that does not collide on concurrent writes? If shared, what is the conflict-resolution story for two hosts
  appending the same second?
- Should the schema migration to v2 be done as one atomic bump or split into "tolerant reader ships first, writer
  ships next release" (recommendation N)? The latter is safer but doubles the change-set count.
- Should hooks ever block a memory read (recommendation R)? A `before_memory_read` veto is powerful but also a footgun
  if a broken hook locks all agents out of long-term memory mid-session.
- Should citation events (recommendation S) flow through the same JSONL log as read events, or live in a sibling file?
  Same file is simpler to consume; separate files keep schema-v2 cleaner.

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
- `src/sase/memory/proposals/ledger.py`
- `src/sase/ace/tui/memory_reads.py`
- `src/sase/ace/tui/widgets/prompt_panel/_agent_memory_reads.py`
- `tests/test_memory_read_log.py`
- `memory/short/gotchas.md`
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
- Anthropic context engineering for agents: https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents
- Basic Memory CLI overview: https://www.mintlify.com/basicmachines-co/basic-memory/api/cli/overview
- Goose memory MCP docs: https://goose-docs.ai/docs/mcp/memory-mcp/
- Evaluating AGENTS.md: https://arxiv.org/abs/2602.11988
- Unit 42 memory poisoning writeup:
  https://unit42.paloaltonetworks.com/indirect-prompt-injection-poisons-ai-longterm-memory/
- "Poison Once, Exploit Forever" arXiv: https://arxiv.org/abs/2604.02623
- "Zombie Agents" arXiv: https://arxiv.org/abs/2602.15654
- "Memory Poisoning Attack and Defense on Memory Based LLM-Agents": https://huggingface.co/papers/2601.05504
- Model Context Protocol specification: https://spec.modelcontextprotocol.io/
- Model Context Protocol overview: https://modelcontextprotocol.io/
- POSIX `fcntl` advisory locking (Linux man page): https://man7.org/linux/man-pages/man2/fcntl.2.html
- JSON Lines format (concurrent-append constraints): https://jsonlines.org/
