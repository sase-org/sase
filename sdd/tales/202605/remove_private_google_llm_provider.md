---
create_time: 2026-05-07 12:09:20
status: done
---
# Remove private Google LLM provider references from sase

## Goal

Remove repo-local references to the Google-private LLM provider that now belongs only in the private `../retired Mercurial plugin`
plugin repository. The public `sase` repo should continue to describe external LLM provider plugins generically without
naming or documenting that private provider, its CLI, model names, environment variables, skill deploy path, or Python
implementation paths.

## Current Inventory

The repo no longer appears to contain in-tree provider implementation code or tests for this provider. The remaining
references are documentation, memory, skill targeting metadata, and historical SDD artifacts.

Live, non-SDD references:

- `README.md`: supported-agent table and LLM provider feature summary name the private provider as available through
  `retired Mercurial plugin`.
- `docs/plugins.md`: plugin group examples, `retired Mercurial plugin` package description, entry-point table, and LLM plugin section
  name the private provider and document its special skill path.
- `docs/llms.md`: overview, external provider section, model-name hook example, and environment variable section name
  the private provider and document private implementation details.
- `docs/xprompt.md`: negative-keyword YAML example uses the private provider name even though the concept is generic.
- `memory/short/gotchas.md`: contains provider-specific operational guidance and a generic YAML example using the
  private name.
- `memory/long/external_repos.md`: lists the private provider as part of `../retired Mercurial plugin`.
- `memory/long/generated_skills.md`: commit-skill matrix and prose include the private provider runtime.
- `src/sase/xprompts/skills/sase_hg_commit.md`: frontmatter installs the Mercurial commit skill for `gemini` and the
  private runtime.

Historical SDD references:

- Many `sdd/prompts`, `sdd/tales`, `sdd/research`, and `sdd/epics` files from 202604 and 202605 include the provider
  name, CLI name, model name, entry-point path, or implementation details.
- Some SDD references are incidental examples; several files are dedicated provider implementation/fix plans.
- `sdd/beads/issues.jsonl` contains closed issue descriptions for the old provider migration work.

## Approach

1. Preserve the plugin architecture while removing private-provider specifics.
   - Keep docs saying `sase_llm` supports built-in providers and optional external provider plugins.
   - Keep `retired Mercurial plugin` documented as the Mercurial/GitHub-internal VCS/config/xprompt plugin where appropriate, but do
     not mention a private LLM provider.
   - Replace provider-specific examples with generic external-provider examples that do not expose private names,
     models, paths, or env vars.

2. Remove runtime targeting from core skill source.
   - Change `src/sase/xprompts/skills/sase_hg_commit.md` to target only public/core runtimes that should receive this
     core skill.
   - Update generated-skill memory so it no longer claims that the private runtime receives core-generated skills.
   - Do not add replacement behavior for the private provider in this repo; any provider-specific skill generation
     belongs in `../retired Mercurial plugin`.

3. Clean live memory and docs.
   - Delete the provider-specific gotcha from `memory/short/gotchas.md`.
   - Remove the private-provider keyword/detail from `memory/long/external_repos.md`.
   - Replace the negative-keyword examples in docs/memory with neutral examples.
   - Update README and docs so all public provider lists are Claude, Codex, Gemini, Qwen, and OpenCode, plus generic
     external plugins.

4. Redact or remove historical SDD references.
   - For current/forward-looking SDD documents, rewrite mentions to generic "external LLM provider" language when the
     surrounding content is still useful.
   - For dedicated historical private-provider implementation/debug artifacts, prefer deletion over heavy redaction
     because the files mainly preserve private names, commands, model names, and implementation paths.
   - For bead history in `sdd/beads/issues.jsonl`, redact private-provider names and paths to generic external-provider
     wording while preserving the fact that closed migration work happened.
   - If SDD link validation flags deleted prompt/tale pairs, either remove both sides of the obsolete pair together or
     use the repo's SDD repair/validation workflow to keep remaining metadata coherent.

5. Verify with case-insensitive searches.
   - Run targeted search over the full repo for the private provider name plus known variants: provider class name,
     plugin module path, CLI binary name, default model name, env var prefix, and skill deploy path.
   - Run broader source checks to ensure no accidental provider-specific branching remains in `src/` or `tests/`.
   - Because this repo's memory says to run `just install` before checks in ephemeral workspaces, run `just install`
     followed by `just check` after edits.

## Expected Edited Areas

- `README.md`
- `docs/llms.md`
- `docs/plugins.md`
- `docs/xprompt.md`
- `memory/short/gotchas.md`
- `memory/long/external_repos.md`
- `memory/long/generated_skills.md`
- `src/sase/xprompts/skills/sase_hg_commit.md`
- `sdd/**` historical markdown and bead JSON lines containing private-provider references

## Non-Goals

- Do not edit `../retired Mercurial plugin` unless verification proves this repo depends on a cross-repo change.
- Do not remove the `sase_llm` plugin system or generic external-provider support.
- Do not introduce provider-specific compatibility shims in public `sase`.

## Risks

- Historical SDD cleanup can disturb prompt/tale links if only one side of a pair is deleted. Delete or redact paired
  files consistently and run SDD validation.
- Removing the private runtime from `sase_hg_commit` means this core repo no longer generates that skill for the private
  provider. That is intentional for this cleanup; the private plugin repo should own private-provider skill wiring.
- A literal search can miss variants in filenames. Include filename searches as well as content searches.
