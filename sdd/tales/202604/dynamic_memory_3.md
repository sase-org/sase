---
create_time: 2026-04-12 20:39:14
status: done
prompt: sdd/prompts/202604/dynamic_memory_3.md
---

# Plan: Dynamic Memory Generation with TUI Visibility

## Goal

Before each agent session, scan the user's expanded prompt against keyword-tagged memory xprompts and write
`memory/dynamic.md` containing `@` references to the matched tier 3 files. The agent runtime already reads
`@memory/dynamic.md` from AGENTS.md when the file exists on disk. Save structured match data as an artifact so the TUI
can show exactly which memories were loaded and why.

## Approach: `keywords` field + `memory` tag (Approach A)

Extend the xprompt system with two additions:

1. A `keywords: list[str]` field on `XPrompt` for matching against prompts.
2. A `memory` value on `XPromptTag` for routing matched xprompts to dynamic memory generation.

Memory xprompts are defined in `default_config.yml` with `content: "@memory/long/..."` references, keeping tier 3 files
as the single source of truth. When matched, the literal `@memory/long/...` string is written to `memory/dynamic.md`,
and the agent runtime resolves it to actual file content during its `@` import chain.

## Changes

### Phase 1: Model and Parsing

**1a. Add `memory` tag** -- `src/sase/xprompt/tags.py`

Add `memory = "memory"` to `XPromptTag` enum.

**1b. Add `keywords` field to `XPrompt`** -- `src/sase/xprompt/models.py`

Add `keywords: list[str] = field(default_factory=list)` after the `skill` field.

**1c. Parse `keywords` in file loader** -- `src/sase/xprompt/loader.py`

In `_load_xprompt_from_file()`, extract `front_matter.get("keywords", [])` and pass to `XPrompt(keywords=...)`.

**1d. Parse `keywords` in config parser** -- `src/sase/xprompt/loader_parsing.py`

In `parse_xprompt_entries()`, for structured dict entries read `value.get("keywords", [])` and pass to
`XPrompt(keywords=...)`.

**1e. Propagate through Workflow** -- `src/sase/xprompt/workflow_models.py` and `models.py`

- Add `keywords: list[str] = field(default_factory=list)` to `Workflow` dataclass.
- Pass `keywords=xprompt.keywords` in `xprompt_to_workflow()`.

### Phase 2: Generation Logic

**2a. Create `src/sase/memory/dynamic.py`**

```python
@dataclass
class MatchedMemory:
    """A memory xprompt that matched the user's prompt."""
    name: str
    keywords_matched: list[str]
    content: str

def generate_dynamic_memory(
    prompt: str, workspace_dir: str, project: str | None
) -> list[MatchedMemory]:
```

Logic:

- Load all prompts via `get_all_prompts(project=project)`.
- Filter to those with `XPromptTag.memory` and non-empty `keywords`.
- For each, collect keywords that match the prompt (case-insensitive substring).
- If any keyword matches, append to results with the matched keywords and content.
- If results: write concatenated content to `{workspace_dir}/memory/dynamic.md`.
- If no results: remove `memory/dynamic.md` if it exists (cleanup from prior run).
- Return `list[MatchedMemory]` for the caller to save as an artifact.

### Phase 3: Runner Integration + Artifact

**3a. Wire into `src/sase/axe/run_agent_runner.py`**

Insert after `os.chdir(workspace_dir)` (line 217), before `extract_directives_and_write_meta()` (line 220). At this
point the expanded prompt is available and workspace is prepared.

```python
from sase.memory.dynamic import generate_dynamic_memory

matched = generate_dynamic_memory(prompt, workspace_dir, project_name)
if matched:
    # Save structured artifact for TUI
    artifact = [
        {"name": m.name, "keywords_matched": m.keywords_matched, "content": m.content}
        for m in matched
    ]
    with open(os.path.join(artifacts_dir, "dynamic_memory.json"), "w") as f:
        json.dump(artifact, f, indent=2)
```

Also print a console section for the runner's stdout log:

```
=== Dynamic Memory ===
+ memory/external_repos (matched: chezmoi, plugin)
+ memory/generated_skills (matched: skill)
======================
```

### Phase 4: Config Entries

**4a. Add memory xprompts to `src/sase/default_config.yml`**

```yaml
memory/external_repos:
  tags: memory
  keywords: [chezmoi, plugin, sase-github, retired Mercurial plugin, sase-telegram, sase-nvim, dotfile, cross-repo]
  content: "@memory/long/external_repos.md"
memory/generated_skills:
  tags: memory
  keywords: [skill, SKILL.md, init-skills, sase_commit, sase_git_commit, sase_hg_commit, commit workflow, commit skill]
  content: "@memory/long/generated_skills.md"
```

Content is a literal `@` reference string. When written to `memory/dynamic.md`, the agent runtime resolves it as part of
the CLAUDE.md -> AGENTS.md -> `@memory/dynamic.md` inclusion chain.

### Phase 5: TUI Display

**5a. Add artifact reader** -- `src/sase/ace/tui/models/agent_artifacts.py`

```python
def get_dynamic_memory_info(agent: Agent) -> list[dict] | None:
    """Load dynamic memory match info from artifacts."""
```

Reads `dynamic_memory.json` from the agent's artifacts directory.

**5b. Display in agent prompt panel** -- `src/sase/ace/tui/widgets/prompt_panel/_agent_display.py`

Add a "DYNAMIC MEMORY" section in the agent xprompt display area (after the AGENT XPROMPT section, before AGENT PROMPT).
Show while the agent is running/waiting (same lifecycle as the xprompt section).

Visual design:

```
DYNAMIC MEMORY
  + external_repos  (matched: chezmoi, plugin)
  + generated_skills  (matched: skill, SKILL.md)

──────────────────────────────────────────────────
```

- Header: `bold #D7AF5F underline` (matches existing section headers)
- Each entry: `+` in green (`#00D7AF`), name in white, matched keywords in dim
- Divider: standard `─` \* 50 in dim (matches existing pattern)

If no dynamic memory was matched, the section is omitted entirely (no "none matched" message).

### Phase 6: .gitignore

**6a. Update `.gitignore`**

Add `memory/dynamic.md` to prevent accidental commits of generated files.

### Phase 7: Tests

- `parse_tags("memory")` returns `frozenset({XPromptTag.memory})`.
- `parse_tags` all-values test updated to include `memory`.
- `parse_xprompt_entries()` with `keywords` field produces `XPrompt` with correct keywords.
- `_load_xprompt_from_file()` with keywords front matter produces correct XPrompt.
- `generate_dynamic_memory()`: matching keywords writes file, no matches removes file, multiple matches concatenated,
  returns structured `MatchedMemory` list.

### Phase 8: Validation

Run `just install && just check`.

## Key Design Decisions

- **`@` references as content** -- Memory xprompts contain literal `@memory/long/foo.md` strings. The agent runtime
  resolves these, not sase. Tier 3 files remain the single source of truth.
- **Dual access** -- When keywords match, tier 3 content is auto-included. When they don't, agents still see the tier 3
  listing in AGENTS.md and can read on demand. No information is lost.
- **Artifact-based TUI** -- Match results saved as `dynamic_memory.json` so the TUI can display them without re-running
  the matching logic. This is the same pattern used for `agent_meta.json`, `workflow_state.json`, etc.
- **Case-insensitive substring matching** -- Over-inclusion is cheap (tier 3 is ~60 lines total). Under-inclusion (agent
  missing relevant context) is the worse failure mode.
