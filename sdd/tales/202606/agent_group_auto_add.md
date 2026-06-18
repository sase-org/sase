---
create_time: 2026-06-18 09:59:16
status: done
prompt: sdd/prompts/202606/agent_group_auto_add.md
---
# Plan: Auto-Add Named Agents To Existing Groups

## Goal

When a launched SASE agent has a resolved name that matches an existing agent group name exactly, or begins with that
group name followed by `.`, automatically assign the agent to that group. This lets one prompt establish the group with
`%group`/`%g`, then later prompts use `%name`/`%n`, wait-derived names, fork-derived names, template-derived names, or
planned names to land in the same group without repeating `%g`.

## Current Shape

Agent groups in the Agents tab are backed by the user-managed agent tag store at `~/.sase/agent_tags.json`.
`%group`/`%g` parses into `PromptDirectives.tag`, is written into `agent_meta.json` as `tag`, and is persisted through
`sase.ace.agent_tags.update_agent_tag()` when the runner has a `cl_name` identity.

The final agent name is not always the raw `%name` directive. `run_agent_directives.extract_directives_and_write_meta()`
resolves explicit names, planned names, template names, `#fork` names (`foo.f1`), `%wait` names (`foo.w1`), repeat
names, and automatic names before writing metadata and claiming the name. That final resolved name is the right source
for auto-grouping.

## Product Rules

1. Explicit `%group` always wins. If the prompt supplies `%g:bar`, the agent is assigned to `bar` even if its name would
   match an existing `foo` group.
2. Auto-grouping only happens when there is a final resolved agent name and no explicit group directive.
3. A group exists when that group name is already present as a value in `agent_tags.json`. Auto-grouping does not create
   new groups.
4. Matching is dot-boundary-aware:
   - `foo` matches group `foo`
   - `foo.bar` matches group `foo`
   - `foobar` does not match group `foo`
5. If multiple existing groups match, choose the longest matching group name. This preserves dotted groups such as
   `sase-42.3`, where `sase-42.3.1` should go to `sase-42.3` when that group already exists.
6. Auto-assignment should write the same metadata shape as explicit `%group`: `agent_meta.json["tag"]`, `AgentInfo.tag`,
   and the persisted tag store when the runner has an identity.

## Implementation Plan

1. Add focused helpers in `src/sase/ace/agent_tags.py`.
   - Add a small matcher that accepts an agent name and known group names, returning the longest exact/dotted-prefix
     match.
   - Add an atomic helper such as `update_agent_tag_from_existing_name_group(identity, agent_name) -> str | None` that
     locks `agent_tags.json`, loads current tags, finds the matching existing group, persists the identity if found, and
     returns the chosen group.
   - Keep validation behavior centralized through existing tag loading and `set_tag()`.

2. Integrate at the runner metadata boundary in `src/sase/axe/run_agent_directives.py`.
   - After the final `agent_name` has been resolved and before `agent_meta` is written, compute `agent_tag` as
     `directives.tag` if present, otherwise the best existing group match for `agent_name`.
   - Put `agent_tag` into `agent_meta["tag"]` when present so snapshot/wire loaders and immediate filesystem loaders see
     the same group assignment.
   - After name claim and metadata write, persist the tag store:
     - explicit `%group`: keep the existing update path
     - implicit match: use the new atomic helper, or use a shared helper that handles both explicit and implicit paths
   - Keep the current `cl_name` guard for tag-store persistence, matching existing `%group` behavior;
     `agent_meta["tag"]` still carries the value for loaders that read the artifacts directly.

3. Avoid changing directive parsing or TUI grouping.
   - `%group` validation and parsing already work.
   - Agent panels already derive groups from tags and load `agent_meta["tag"]`, then overlay persisted tag assignments.
   - Dotted-name tree grouping remains presentation-only and separate from tag panels.

## Tests

1. `tests/test_agent_tags.py`
   - Matcher returns `foo` for `foo`, `foo.bar`, and `foo.bar.baz`.
   - Matcher does not return `foo` for `foobar`.
   - Longest match wins when both `foo` and `foo.bar` exist.
   - Atomic update helper preserves existing entries and returns `None` without writing when no group matches.

2. `tests/test_axe_run_agent_phases_tags.py` or `tests/test_agent_names_extract.py`
   - Explicit `%group` still persists and wins over an auto-matching group.
   - `%name:foo.child` auto-persists group `foo` when `foo` already exists.
   - A wait-derived name like `%wait:foo` resolves to `foo.w1` and auto-persists group `foo`.
   - A fork-derived name from `#fork:foo` resolves to `foo.f1` and auto-persists group `foo`.
   - A planned/template-derived name such as `build-7` or `sase-42.3.1` uses the final resolved name, not the raw
     template text.
   - No existing group means no `tag` in `agent_meta.json` and no tag-store write.

3. Existing multi-prompt tests should not need behavior changes because planned names are already asserted there; the
   runner-level tests cover the final persisted assignment.

## Verification

Run focused tests first:

```bash
uv run pytest tests/test_agent_tags.py tests/test_axe_run_agent_phases_tags.py tests/test_agent_names_extract.py
```

After source changes, follow repository instructions:

```bash
just install
just check
```

## Risks And Decisions

1. The main ambiguity is whether matching should use only the first dotted segment or the longest existing dotted group.
   The longest-match rule handles the simple `foo` case and supports existing dotted groups without extra syntax.
2. If an explicit `%g:foo` launch and an implicit `foo.child` launch happen concurrently, the implicit launch only joins
   the group if it sees `foo` in the current tag store. This is consistent with the "if such a group already exists"
   rule; subsequent launches will join reliably.
3. This is launch metadata behavior, not a cross-frontend core algorithm yet. The persisted artifact/tag-store result is
   still consumable by other frontends through existing scan wire fields.
