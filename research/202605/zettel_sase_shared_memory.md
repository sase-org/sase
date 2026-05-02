# Zettel as Shared Human/Agent Memory in SASE

## Question

Can zettel become a useful shared memory layer between humans and SASE agents?

My short answer: yes, but it should not start as "agents write straight into the canonical zettelkasten." The useful
shape is a two-layer system:

1. **Canonical zettel** are curated, human-readable, linked knowledge objects.
2. **SASE memory projections** are generated or selected views of those zettel for agents: `memory/short`, `memory/long`,
   dynamic memory, skills, project plans, and review checklists.

This preserves what is valuable about zettel -- deliberate linking, atomicity, revision by later notes, and visible
structure -- while giving agents fast, deterministic context at runtime.

## Local Notes Reviewed

The strongest local evidence came from these `~/org` notes:

| File | Relevant ideas |
| --- | --- |
| `~/org/zorg_term.zo` | Defines `~/org` itself as the Zettelkasten; a zettel can be a file, directory, or note with an ID. |
| `~/org/zorg_ideas_2503.zo` | `@foo/bar` ID syntax, file zettels, note blocks, query zettels, note types, sibling/child link syntax. |
| `~/org/zorg_ideas_2504.zo` | Jumpers across explicit, inherited, incoming, and Folgezettel-like relationships. |
| `~/org/zorg_v2_design.zo` | Design outline for Zorg v2; explicitly asks how `@foo/bar/baz` compares to Folgezettel IDs. |
| `~/org/z_tags.zo` | Tags as links to zettel; property keys as links; `#foo/bar` subzettel links. |
| `~/org/bobdoto_ref.zo` | Hub/structure notes, clusters, literature notes, Folgezettel as useful friction. |
| `~/org/lit/system_for_writing.zo` | Zettel workflow, atomicity, contextualized links, hub notes, logs, and "do not revise away old notes." |
| `~/org/lit/zettel_method.zo` | Inbox-first processing, small/atomic notes, explicit linking. |
| `~/org/lit/understand_folgezettel.zo` | Folgezettel as a lightweight relation that can be clarified later; concern about mere connection collection. |

The local direction is already coherent: zettel are not just markdown blobs. They are addressable thoughts in a linked
system, with file/directory/note identity, typed notes, query-derived views, and navigation affordances.

## Relevant SASE Context

SASE already has the pieces needed for a first integration:

- `memory/short/*.md` is always loaded through `AGENTS.md`.
- `memory/long/*.md` is a long-term memory pool with `keywords` frontmatter.
- `src/sase/memory/dynamic.py` matches memory keywords against the prompt, writes matched files into `.sase/memory/`,
  and injects a `### DYNAMIC MEMORY` section into the prompt.
- `src/sase/xprompt/loader.py` auto-discovers `memory/long/*.md` files as memory xprompts when they have `keywords`
  frontmatter.
- Existing research already recommends git-versioned memory and project-local state in `.sase/memory/`.

The important detail: dynamic memory today is already a projection system. It takes authored markdown and turns it into
agent-ready prompt context. Zettel can become another authored source feeding that projection.

## External Research Notes

### Zettelkasten is a communication partner, not a topic folder

Luhmann's "Communication with Zettelkastens" argues against topically ordered note storage and for fixed placement plus
rich references. The key design ideas for SASE are:

- stable IDs matter more than topical folders;
- cross-references solve multi-placement without duplicating notes;
- a keyword/index layer is needed because the system is not topically ordered;
- value comes from relational surprise, not just stored content.

Source: [Improved Translation of "Communications with Zettelkastens"](https://zettelkasten.de/communications-with-zettelkastens/).

The practical takeaway for SASE: a zettel memory layer should preserve stable IDs and link structure, then expose search
and projections over that graph. It should not be a folder-per-topic document dump.

### Modern zettel practice emphasizes note processing

The Zettelkasten.de overview points readers to Luhmann history, the communication essay, and note-focused workflow
materials rather than treating the method as a software feature list. Your local notes align with this: fleeting notes
and literature notes get processed into main notes, and structure/hub notes track developing trains of thought.

Sources:

- [Zettelkasten.de Getting Started](https://zettelkasten.de/overview/)
- [Zettelkasten.de home](https://zettelkasten.de/)

The practical takeaway for SASE: raw agent transcripts are not zettel. They are capture material. Agents can propose
zettel, but humans or a distillation workflow should decide what enters canonical memory.

### Agent memory needs write, manage, read loops

Recent agent-memory research is converging on memory as an explicit system, not "just include chat history":

- Reflexion stores verbal reflections in episodic memory and uses them to improve future decisions.
- Generative Agents store natural-language experiences, synthesize higher-level reflections, and retrieve dynamically
  for planning.
- CoALA frames agents around modular memory plus actions that interact with internal and external state.
- MemGPT treats context as a memory hierarchy, paging between limited main context and larger stores.
- Recent surveys formalize agent memory as a write-manage-read loop and emphasize filtering, contradiction handling,
  latency budgets, and privacy.

Sources:

- [Reflexion: Language Agents with Verbal Reinforcement Learning](https://arxiv.org/abs/2303.11366)
- [Generative Agents: Interactive Simulacra of Human Behavior](https://arxiv.org/abs/2304.03442)
- [Cognitive Architectures for Language Agents](https://arxiv.org/abs/2309.02427)
- [MemGPT: Towards LLMs as Operating Systems](https://arxiv.org/abs/2310.08560)
- [Memory for Autonomous LLM Agents](https://arxiv.org/abs/2603.07670)

The practical takeaway for SASE: zettel should sit in the **manage** layer. SASE should not simply retrieve old chats.
It should turn selected experiences into durable semantic/procedural memory and keep raw episodic logs separate.

### Memory structure matters

The "Structural Memory of LLM Agents" paper compares chunks, triples, atomic facts, summaries, mixed memory, and
retrieval methods. Its key implication is that no one structure wins universally; mixed structures are resilient, and
iterative retrieval performs well.

Source: [On the Structural Memory of LLM Agents](https://arxiv.org/abs/2412.15266).

The practical takeaway for SASE: zettel should not replace all memory structures. Use zettel as the canonical authored
layer, but allow projections into:

- compact markdown chunks for dynamic memory;
- graph edges for link/query navigation;
- structured triples or metadata for search, drift checks, and dashboards;
- procedural snippets for skills and `AGENTS.md`.

## Review of Your Zettel Thoughts

Your notes have three especially good instincts for SASE:

1. **Treat files and directories as zettel.** This maps cleanly to software projects. A package, subsystem, command, or
   workflow can have a zettel identity independent of where the supporting source files live.
2. **Make queries into zettel.** `zorg_query_zettel` is directly relevant to SASE dynamic memory: a "memory view" can be
   a note with a query, not a static manually maintained document.
3. **Prefer typed notes over loose properties.** `zorg_note_types` maps well onto agent memory types: `&fact`, `&howto`,
   `&gotcha`, `&decision`, `&episode`, `&source`, `&question`, `&index`.

The main risk in the notes is letting ID/link machinery dominate the shared-memory goal. Folgezettel-like IDs and
`@foo/bar` paths are useful because they force placement and reveal structure, but SASE agents primarily need:

- what is true;
- when it became true;
- what source supports it;
- what code/files it applies to;
- how confident the system is;
- whether it should be injected automatically.

So I would make zettel IDs stable and expressive, but not require every agent memory to be manually placed in a perfect
branch at capture time.

## Proposed Model

### Memory Types

Use zettel note types that align with agent memory needs:

| Type | Purpose | Agent projection |
| --- | --- | --- |
| `&fact` | Durable project/domain fact | Dynamic memory, search result |
| `&howto` | Procedural workflow | Skill, `memory/long`, checklist |
| `&gotcha` | Known failure mode | `memory/short` if critical, otherwise dynamic memory |
| `&decision` | Design decision and rationale | AGENTS/context, research, drift check |
| `&episode` | Specific event/run outcome | Usually not injected directly; input to distillation |
| `&source` | Literature/reference note | Citation/provenance, rarely injected directly |
| `&index` | Hub/structure note | Navigation and query seed |
| `&query` | Computed memory view | Dynamic memory source |

This gives humans a coherent system and gives SASE a projection contract.

### Minimal Zettel Shape

For SASE memory, each canonical zettel should have enough metadata for deterministic retrieval:

```text
@sase/memory/dynamic-keywords &howto #sase #memory
Short title or claim.

WHY:
- The problem this solves.

CONTENT:
- The actual reusable knowledge.

APPLIES:
- src/sase/memory/dynamic.py
- src/sase/xprompt/loader.py

TRIGGERS:
- dynamic memory
- keywords
- memory/long

PROVENANCE:
- research/202604/dynamic_memory_critique.md
- agent/session id or human note
```

Zorg syntax can evolve, but SASE should normalize the parsed shape into a simple record:

```json
{
  "id": "@sase/memory/dynamic-keywords",
  "type": "howto",
  "links": ["#sase", "#memory"],
  "applies_to": ["src/sase/memory/dynamic.py"],
  "triggers": ["dynamic memory", "keywords"],
  "provenance": ["research/202604/dynamic_memory_critique.md"],
  "body": "..."
}
```

## Integration Architecture

### Phase 1: Read-only zettel projection into SASE memory

Start by letting SASE read curated zettel and generate memory files. Do not let agents write canonical `~/org` notes yet.

Pipeline:

```text
~/org zettel
  -> zettel parser/indexer
  -> selected SASE memory zettel
  -> generated memory/long/*.md
  -> existing dynamic memory injection
```

Implementation sketch:

1. Add a command like `sase memory import-zettel --source ~/org --project sase`.
2. Select zettel by explicit tag/link/type, e.g. `#sase` plus `&howto|&gotcha|&decision|&fact`.
3. Generate `memory/long/generated-zettel-*.md` or `.sase/memory/zettel/*.md`.
4. Preserve provenance back to the original zettel ID and file path.
5. Use existing `keywords` frontmatter so no dynamic-memory runtime changes are needed.

This tests the value quickly using existing machinery.

### Phase 2: Project-local zettel memory in `.sase/memory/`

Create a project-local canonical memory store:

```text
.sase/memory/
  zettel/
    index.md
    dynamic-memory.md
    rust-core-boundary.md
    tui-testing.md
  projections/
    long-dynamic-memory.md
    skill-sase-beads.md
```

The `zettel/` directory is human/agent curated. The `projections/` directory is generated.

This matches existing multi-machine research: project-local state like `.sase/memory/` should travel with project VCS or
a project-local state repo, not with global `~/.sase` sync.

### Phase 3: Agent proposal workflow

Agents should write proposals, not canonical memories:

```text
.sase/memory/inbox/
  20260502-1530-agent-name.md
```

Each proposal should include:

- observed problem or lesson;
- suggested zettel type;
- proposed ID;
- source files/commands/artifacts;
- confidence;
- whether this should become dynamic memory, a skill, or short memory.

A human or a dedicated distiller command can promote inbox items into canonical zettel. This avoids memory poisoning,
stale claims, and low-quality chat-summary accumulation.

### Phase 4: Agent-initiated retrieval

Once the memory pool grows, add an explicit retrieval surface:

```bash
sase memory search "dynamic memory stale files"
sase memory show @sase/memory/dynamic-keywords
sase memory related src/sase/memory/dynamic.py
```

This complements pre-session dynamic memory. Pre-session keyword injection handles obvious cases; agent-initiated
retrieval handles discoveries made mid-task.

## Dynamic Memory Mapping

Your zettel system can make dynamic memory better in three ways:

1. **Keywords come from zettel triggers.** A zettel's `TRIGGERS` section can generate the `keywords` frontmatter used by
   `memory/long/*.md`.
2. **Path triggers come from `APPLIES`.** Existing research recommends file-pattern triggers. Zettel already want to
   know what code they apply to.
3. **Structure notes become memory bundles.** A hub/index zettel can generate one memory file that includes several
   child zettel, preserving link context.

Example generated projection:

```markdown
---
keywords: [dynamic memory, memory/long, XPromptTag.memory, ".sase/memory"]
source_zettel: "@sase/memory/dynamic"
applies_to:
  - src/sase/memory/dynamic.py
  - src/sase/xprompt/loader.py
---

# Dynamic Memory

Derived from @sase/memory/dynamic.

...
```

No SASE runtime change is required for the first version because `memory/long/*.md` with `keywords` already works.

## Design Decisions

### Do not use vector search as the first integration

Vector search is useful later, but it is the wrong first abstraction. Your notes are already link-rich and ID-rich.
SASE already has keyword-driven dynamic memory. Start with deterministic structure:

- zettel IDs;
- links;
- note types;
- triggers;
- applies-to paths;
- provenance.

Add embeddings only when keyword/path/link retrieval stops being good enough.

### Do not make raw chats canonical memory

SASE chats and artifacts are episodic evidence. They can feed distillation, but they should not become canonical shared
memory by default. Otherwise the memory layer becomes a searchable transcript pile instead of a thinking system.

### Do allow contradictions

Your `system_for_writing` notes already point at the Luhmann-style pattern of revising by later entries rather than
erasing older ones. That is useful for SASE. A memory zettel should be able to say:

- supersedes `@old`;
- contradicts `@old`;
- applies before/after commit `X`;
- obsolete since date `Y`.

This is better than silently editing history, especially for agents trying to understand why a convention changed.

## Recommended First Experiment

Create one project-local zettel-backed memory area for SASE itself:

```text
.sase/memory/zettel/
  index.md
  dynamic-memory.md
  git-versioned-memory.md
  rust-core-boundary.md
  generated-skills.md
```

Then add a generator that emits:

```text
memory/long/zettel_dynamic_memory.md
memory/long/zettel_git_versioned_memory.md
memory/long/zettel_generated_skills.md
```

Each generated file should have `keywords` frontmatter and a provenance footer pointing back to the zettel.

Pick dynamic memory as the first subject because:

- it already exists;
- there is prior research and critique;
- the code path is small;
- keyword/frontmatter projection maps directly to existing behavior;
- it will exercise stale-memory and path-trigger ideas quickly.

## Open Questions

1. Should canonical shared zettel live in `~/org`, project `.sase/memory/zettel`, or both with sync/import rules?
2. Should SASE support Zorg syntax directly, or should the first prototype use Markdown with a small YAML/schema layer?
3. What is the promotion workflow from `.sase/memory/inbox` into canonical zettel?
4. Should memory zettel be reviewed in normal code review, or through a separate "memory review" command?
5. How should SASE detect stale zettel when related source files change?

## Recommendation

Build zettel into SASE as a **curated memory source and projection layer**, not as an agent scratchpad.

The first useful version should be boring:

1. Parse selected zettel from `~/org` or `.sase/memory/zettel`.
2. Generate `memory/long/*.md` files with `keywords` frontmatter.
3. Let the existing dynamic-memory system inject those files.
4. Let agents propose new memory zettel into an inbox.
5. Promote proposals manually until the workflow proves itself.

That gives humans and agents a shared memory substrate without losing the deliberate processing discipline that makes
zettel valuable in the first place.

## Sources

Local:

- `~/org/zorg_term.zo`
- `~/org/zorg_ideas_2503.zo`
- `~/org/zorg_ideas_2504.zo`
- `~/org/zorg_v2_design.zo`
- `~/org/z_tags.zo`
- `~/org/bobdoto_ref.zo`
- `~/org/lit/system_for_writing.zo`
- `~/org/lit/zettel_method.zo`
- `~/org/lit/understand_folgezettel.zo`
- `research/202604/dynamic_memory_implementation.md`
- `research/202604/dynamic_memory_critique.md`
- `research/202604/git_versioned_agent_memory.md`
- `research/202604/codified_context_paper_insights.md`
- `research/202605/multi_machine_sync.md`

External:

- [Zettelkasten.de](https://zettelkasten.de/)
- [Zettelkasten.de Getting Started](https://zettelkasten.de/overview/)
- [Improved Translation of "Communications with Zettelkastens"](https://zettelkasten.de/communications-with-zettelkastens/)
- [Reflexion: Language Agents with Verbal Reinforcement Learning](https://arxiv.org/abs/2303.11366)
- [Generative Agents: Interactive Simulacra of Human Behavior](https://arxiv.org/abs/2304.03442)
- [Cognitive Architectures for Language Agents](https://arxiv.org/abs/2309.02427)
- [MemGPT: Towards LLMs as Operating Systems](https://arxiv.org/abs/2310.08560)
- [On the Structural Memory of LLM Agents](https://arxiv.org/abs/2412.15266)
- [Memory for Autonomous LLM Agents](https://arxiv.org/abs/2603.07670)
