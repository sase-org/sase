# Research: `sase init-skills` Command

## Problem Statement

Agent skills (SKILL.md files for Claude, Gemini, Codex) are currently maintained manually in the chezmoi repo at
`~/.local/share/chezmoi/home/dot_<provider>/skills/<name>/SKILL.md`. This creates maintenance burden:

- Content must be duplicated across providers (mostly identical with minor wording tweaks)
- Adding a new skill requires creating 3+ files manually
- No single source of truth for skill definitions
- Skills are disconnected from the xprompt system that powers most of sase's prompt infrastructure

**Goal**: Add a `sase init-skills` command that generates and deploys skill files from a single source of truth,
leveraging the existing xprompt infrastructure where appropriate.

---

## Current State

### Skill Format (SKILL.md)

```yaml
---
name: sase_plan
description: Create an implementation plan. Use instead of plan mode (which is disabled).
---
Use this skill when you need to plan before implementing...
```

### Deployment Targets

| Provider | Chezmoi Source                                                  | Deployed To                        |
| -------- | --------------------------------------------------------------- | ---------------------------------- |
| Claude   | `~/.local/share/chezmoi/home/dot_claude/skills/<name>/SKILL.md` | `~/.claude/skills/<name>/SKILL.md` |
| Gemini   | `~/.local/share/chezmoi/home/dot_gemini/skills/<name>/SKILL.md` | `~/.gemini/skills/<name>/SKILL.md` |
| Codex    | `~/.local/share/chezmoi/home/dot_codex/skills/<name>/SKILL.md`  | `~/.codex/skills/<name>/SKILL.md`  |

### Existing XPrompt Data Model

```python
@dataclass
class XPrompt:
    name: str
    content: str
    inputs: list[InputArg]
    source_path: str | None
    tags: frozenset[XPromptTag]
    snippet: str | bool | None
```

Frontmatter fields currently parsed: `name`, `input`, `tags`, `snippet`.

### Current Skills

| Skill           | Claude | Gemini | Codex |
| --------------- | ------ | ------ | ----- |
| sase_plan       | Yes    | Yes    | Yes   |
| sase_git_commit | Yes    | Yes    | Yes   |
| sase_questions  | Yes    | Yes    | Yes   |
| sase_beads      | Yes    | Yes    | Yes   |
| sase_hg_commit  | No     | Yes    | No    |

---

## Approach A: XPrompt-Native Skills (Skill Field in Frontmatter)

Add a `skill` field to xprompt YAML frontmatter. The xprompt's content becomes the skill body.

### Schema

```yaml
---
name: sase_plan
skill: true                    # all providers
# OR
skill: [claude, gemini]        # specific providers
description: Create an implementation plan.
---

Use this skill when you need to plan before implementing...
```

### Implementation

1. Add `skill: bool | list[str]` and `description: str` fields to `XPrompt` dataclass
2. Parse `skill` and `description` from frontmatter in `loader.py`
3. `sase init-skills` loads all xprompts, filters for `skill != None`, and generates SKILL.md files
4. Move existing skill `.md` content from chezmoi into xprompt files in the sase repo's `xprompts/` directory (or a
   dedicated `skills/` xprompts directory)

### Generation Logic

```python
def generate_skill_md(xprompt: XPrompt) -> str:
    return f"---\nname: {xprompt.name}\ndescription: {xprompt.description}\n---\n\n{xprompt.content}"
```

### Pros

- Single source of truth: skill content lives alongside other xprompts
- Reuses existing xprompt loader/discovery infrastructure
- Skills can reference other xprompts via `#name` syntax (expanded at init time)
- Minimal new code: mostly wiring up existing systems
- `skill` field is a natural extension of `tags` and `snippet`

### Cons

- XPrompt content model assumes prompt templates (Jinja2, typed inputs); skills are static instruction documents with no
  input args
- Conflates two conceptually different things: "prompt template for expansion" vs "static instructions for an agent
  runtime"
- A skill xprompt with `skill: true` wouldn't normally be used via `#name` expansion (it's not a prompt fragment),
  creating an odd dual-purpose entity
- `description` field doesn't exist on xprompts today and only matters for skills

---

## Approach B: Dedicated `skills/` Directory with Manifest

Keep skills as standalone markdown files in a `skills/` directory within the sase repo, with a YAML manifest declaring
provider targeting.

### Directory Structure

```
src/sase/skills/
  sase_plan.md
  sase_git_commit.md
  sase_questions.md
  sase_beads.md
  sase_hg_commit.md
  manifest.yml
```

### Manifest Format

```yaml
skills:
  sase_plan:
    providers: [claude, gemini, codex]
  sase_git_commit:
    providers: [claude, gemini, codex]
  sase_hg_commit:
    providers: [gemini]
```

### Skill File Format

Same as current SKILL.md format (frontmatter + markdown body). Files are copied as-is to target directories.

### Implementation

1. New `src/sase/skills/` package with bundled skill files
2. `sase init-skills` reads manifest, copies matching skills to provider directories
3. If `use_chezmoi: true`, target is chezmoi source dir; otherwise target is `~/.<provider>/skills/`

### Pros

- Clean separation: skills are clearly their own artifact type
- No changes to xprompt data model
- Easy to understand: "here are the skill files, here's where they go"
- Skill files can be tested/linted independently
- No conceptual confusion about what an xprompt is

### Cons

- Doesn't leverage xprompt infrastructure (discovery, expansion, composition)
- New directory/package to maintain
- Manifest is a parallel registry that could drift from actual files
- Skills can't dynamically compose from xprompt fragments

---

## Approach C: Hybrid (XPrompt Flag + Separate Skill Content)

Use the xprompt `skill` field only as a deployment flag. The actual skill content lives in a separate file referenced by
the xprompt.

### Schema

```yaml
---
name: sase_plan
skill: true
skill_file: skills/sase_plan.md # relative path to actual skill content
---
# This content is for #sase_plan expansion (optional, could be empty)
```

### Pros

- Xprompts stay focused on prompt expansion
- Skill content is separate and purpose-built
- The xprompt acts as a registry entry linking name to skill file

### Cons

- Indirection: two files per skill (xprompt + skill content)
- Unclear benefit over Approach B (manifest already provides the mapping)
- More complex than either A or B alone

---

## Approach D: XPrompt-Native with `prompt_part` Workflow Step

Define skills as xprompt workflows where the only step is a `prompt_part`. The `skill` field on the workflow triggers
SKILL.md generation.

### Schema

```yaml
# xprompts/skills/sase_plan.yml
name: sase_plan
skill: true
tags: []
steps:
  - name: main
    prompt_part: |
      Use this skill when you need to plan before implementing...

      ## Instructions
      1. Explore and understand the problem thoroughly.
      ...
```

### Pros

- Leverages workflow infrastructure (already supports multi-step, conditionals, etc.)
- Could support provider-specific steps: `if: "{{ provider == 'gemini' }}"`
- Consistent with how xprompts already convert to workflows (`xprompt_to_workflow()`)

### Cons

- Overkill: skills are static text, not multi-step workflows
- YAML syntax for multi-line markdown content is awkward (`|` blocks)
- Workflows have inputs, outputs, control flow — none of which skills use

---

## Approach E: XPrompt `.md` Files as Skills (Simplest Path)

Observe that SKILL.md format IS essentially an xprompt `.md` file format (YAML frontmatter + markdown body). Simply add:

1. A `skill` field in frontmatter (already valid YAML the loader can parse)
2. A `description` field in frontmatter (needed for skill metadata)
3. Place skill xprompts in a conventional location (e.g., `xprompts/skills/`)

The xprompt file IS the skill file — `sase init-skills` copies it (with minor frontmatter transformation) to the target
directory.

### Schema

```yaml
# xprompts/skills/sase_plan.md
---
name: sase_plan
description: Create an implementation plan. Use instead of plan mode (which is disabled).
skill: true
---
Use this skill when you need to plan before implementing...
```

### Transformation

When generating SKILL.md, strip the `skill` field from frontmatter (it's deployment metadata, not part of the skill
spec). Keep `name` and `description`.

### Provider Targeting

```yaml
skill: true                   # All providers
skill: [claude, gemini]       # Specific providers
```

### Jinja2 for Provider Variants

For skills that need minor per-provider wording differences:

```yaml
---
name: sase_plan
skill: true
description: Create an implementation plan.
---
Use this skill when you need to plan before implementing. This replaces {{ provider_name }}'s native plan mode, which is
disabled.
```

`sase init-skills` renders with `provider_name` set to "Claude" / "Gemini" / "Codex".

### XPrompt Expansion Within Skills

Since the loader already handles `#name` references, skill content could reference other xprompts:

````yaml
---
name: sase_git_commit
skill: true
description: Commit changes using sase commit.
---

#commit_instructions

## Example

```bash
sase commit -M commit_message.md -f src/auth.py
````

```

`sase init-skills` would expand `#commit_instructions` before writing SKILL.md.

### Implementation Steps

1. Add `skill` and `description` fields to `XPrompt` dataclass
2. Parse these from frontmatter in `loader_parsing.py`
3. Add `xprompts/skills/` directory with migrated skill content
4. New `sase init-skills` command that:
   - Loads all xprompts
   - Filters for those with `skill` field set
   - For each matching provider, renders the content (expanding `#refs`, Jinja2)
   - Writes to target directory (chezmoi source or direct)
5. Remove skill files from chezmoi repo (they're now generated)

### Pros

- Minimal conceptual overhead: SKILL.md format ≈ xprompt .md format
- Single source of truth with no manifest file needed
- Leverages xprompt expansion for DRY skill content
- Jinja2 handles provider-specific variants elegantly
- `description` field is useful beyond skills (could surface in `sase xprompt list`)
- Natural file-per-skill organization in `xprompts/skills/`
- Easy migration path: copy existing SKILL.md content, add `skill: true`

### Cons

- Adds two fields to XPrompt model (`skill`, `description`) that only matter for skill-type
  xprompts
- Skills won't normally be used via `#name` expansion (they're deployment artifacts)
- Need to decide if `xprompts/skills/` is a special subdirectory or just a convention

---

## Comparison Matrix

| Criterion | A (XPrompt Native) | B (Dedicated Dir) | C (Hybrid) | D (Workflow) | E (Simplest) |
|-----------|--------------------|--------------------|------------|--------------|--------------|
| Single source of truth | Yes | Yes | Partial | Yes | Yes |
| Leverages xprompt infra | Full | None | Partial | Full | Full |
| Conceptual clarity | Medium | High | Low | Low | High |
| Implementation effort | Medium | Medium | High | Medium | Low |
| Provider-specific variants | Manual | Manual | Manual | Native (if) | Native (Jinja2) |
| XPrompt expansion in skills | Yes | No | No | Yes | Yes |
| New model fields needed | 2 | 0 | 2 | 1 | 2 |
| Migration effort | Low | Low | Medium | High | Low |

---

## Recommendation: Approach E (XPrompt `.md` Files as Skills)

**Approach E** is the recommended solution because:

1. **Lowest friction**: The SKILL.md format is already nearly identical to xprompt `.md` format.
   Migration is essentially "move files, add `skill: true`."

2. **Leverages existing infrastructure**: XPrompt discovery, loading, Jinja2 rendering, and
   `#ref` expansion all work out of the box. No new subsystems needed.

3. **Jinja2 solves the variant problem**: Instead of maintaining N copies with minor wording
   differences, use `{{ provider_name }}` and render per-provider.

4. **Clean conceptual model**: Skills are xprompts that happen to be deployed as agent skills.
   The `skill` field is analogous to `snippet` — both declare "this xprompt has a secondary
   deployment target beyond prompt expansion."

5. **Minimal model changes**: Only `skill` and `description` fields added to `XPrompt`. The
   `description` field is independently useful for documentation/discoverability.

### Suggested Implementation Plan

1. **Add model fields**: `skill: bool | list[str] | None` and `description: str | None` to
   `XPrompt` dataclass
2. **Update loader**: Parse `skill` and `description` from frontmatter
3. **Create `xprompts/skills/` directory**: Migrate existing skill content from chezmoi
4. **Implement `sase init-skills` command**:
   - Load all xprompts, filter by `skill` field
   - Determine target providers per skill
   - Render content (expand `#refs`, apply Jinja2 with `provider_name` context)
   - Write SKILL.md files to target directories
   - Respect `use_chezmoi` config for path selection
5. **Add `--provider` flag**: Allow running for a single provider (`sase init-skills --provider claude`)
6. **Add `--dry-run` flag**: Show what would be written without writing
7. **Remove skill files from chezmoi**: Replace with generated output from `sase init-skills`
8. **Document**: Update AGENTS.md with `sase init-skills` usage

### Open Questions

- Should `sase init-skills` also handle Claude's `commands/` directory (which has a different
  format from skills)?
- Should there be a `sase init-skills --check` mode that verifies deployed skills match source?
- Should the `description` field support Jinja2 rendering too (for provider-specific trigger
  text)?
- Where should provider-specific skills (like `sase_hg_commit`) live? Same `xprompts/skills/`
  directory with `skill: [gemini]`, or in the retired Mercurial plugin plugin repo?
```
