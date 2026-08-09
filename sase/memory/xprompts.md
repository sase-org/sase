---
type: long
parent: AGENTS.md
description:
  Read before xprompts, prompt directives, or launching agents with git/gh VCS workflow
  blocks.
---

# XPrompts, Directives, and Launch VCS

## Invoke

- `#name` expands inline xprompts/workflows with `prompt_part`; `#!name` launches
  standalone YAML workflows. Marker starts the string or follows whitespace/`([{"'`;
  `# Heading` is ignored.
- Args: `#name(a, b)`, `#name(k=v)` (positional first), quoted comma/special values,
  `[[ ... ]]` multi-line text.
- Shorthands: `#name:arg`, `#name:a,b`, `` #name:`arg with spaces` ``, `#name+` =
  `#name:true`; line `#name: text` captures to blank line, `#name:: text` to next
  line-boundary directive.
- Names: `#ns/name`; `__` -> `/`; aliases `#c` -> `#commit`, `#p` -> `#propose`.
- Literal zones: fenced code and `%xprompts_enabled:false ... :true`. `$(cmd)` in args
  runs shell substitution. Bodies recurse.
- Memory: every flat, non-README `sase/memory/<stem>.md` (or home equivalent) with
  `type: short|long` auto-expands as `#memory/<stem>` (no opt-in, no bare-name alias);
  project shadows home. No args, frontmatter stripped, no `## Children`, no
  `sase memory read` audit event. Ordinary xprompts/config/workflows cannot claim
  `memory/`.

## Directives

`%` directives are stripped before the model sees the prompt and use xprompt arg
grammar.

| Directive                | Alias  | Effect                                                                                |
| ------------------------ | ------ | ------------------------------------------------------------------------------------- |
| `%model:<m>`             | `%m`   | Provider/model; aliases resolve provider; `@effort` ok; quote spaces with `%m("...")` |
| `%effort:<lvl>`          | `%e`   | `none/minimal/low/medium/high/xhigh/max`                                              |
| `%name:<n>`              | `%n`   | Agent name; bare auto-name; `%n(parent, suffix)` plan-family child                    |
| `%clan:<name>`           | `%c`   | Rootless parallel clan; member names must be inside `<clan>.` hood                    |
| `%wait:<n>`              | `%w`   | Dependency; bare = last named; `%wait(time=5m)` / `#t:5m` time floor                  |
| `%repeat:<k>`            | `%r`   | k serial, auto-wait-chained runs                                                      |
| `%auto[:plan/tale/epic]` | `%a`   | Auto-approve next plan; `tale`/`epic` commit SDD then launch follow-up                |
| `%tribe:<name>`          | `%t`   | User-managed tribe, displayed with an `@` prefix                                      |
| `%hide`                  | `%h`   | Hidden row                                                                            |
| `%{a \| b}`              | `%alt` | Branch fan-out; `id=value` ids become suffixes; `%alt(...)` also works                |

`%model` is single-value; fan out models with `%{%m:opus | %m:sonnet}`.

## Define

- **`.md`:** one `prompt_part`; frontmatter
  `name/description/input/tags/snippet/skill/xprompts` (`_` local helpers). Body is
  Jinja2 or `{0}`; `@{{ file }}` inlines a file.
- **Inputs:** `word/line/text/path/int/bool/float`; defaultless means required.
- **`.yml`:** workflow `steps`: `prompt_part/python/bash/agent/use: shared/...`;
  supports `input/output/environment/if/repeat/finally/hidden/tags`.
- **Discovery, first wins:** project `sase/xprompts/` -> legacy project `.xprompts/`,
  `xprompts/` -> home `~/sase/xprompts/` -> legacy home `~/.xprompts/`, `~/xprompts/` ->
  project-specific home `~/sase/xprompts/<project>/` -> legacy
  `~/.config/sase/xprompts/<project>/` -> project/user config -> plugins -> package
  defaults/built-ins. Writers use canonical `sase/` paths only; config/memory collisions
  error while xprompt duplicates shadow lower-priority definitions.
- **Swarm:** top-level `---` outside fences fans out one agent per segment; use `#name`
  for markdown swarms. Embedded swarms put the first segment at the call site, append
  the rest, and inherit leading workspace refs.

## Project-Task Launches

Start project work with a workspace ref; bare prompts normalize to `#git:home`.

| Ref          | Runs in                                          |
| ------------ | ------------------------------------------------ |
| `#gh:<ref>`  | GitHub project, Patch, `owner/repo`, or `@agent` |
| `#git:<ref>` | Bare-git workspace                               |

Append a rollover xprompt for code-changing tasks; each sets `SASE_COMMIT_METHOD` and
injects the no-direct-commit rule.

| XPrompt      | Result                                                   |
| ------------ | -------------------------------------------------------- |
| `#commit`    | Commit on current branch and push; tracked as STITCHES   |
| `#propose`   | Saved diff under `~/.sase/diffs/`, workspace cleaned     |
| `#pr:<name>` | New branch + GitHub PR; Patch status defaults to `draft` |

`#pr(name, status=ready, bug_id=123)` accepts named args, auto-detects PARENT from the
current branch's Patch, and suffixes duplicates with `_<N>`. `#sync` syncs/rebases and
launches conflict help; `#git:<ref>` checks out a ref and reports the diff.

**Rule:** Agents never create git commits, branches, or PRs directly. The
provider-neutral finalizer asks the runtime to use `/sase_git_commit` -> `sase commit`,
honoring `SASE_COMMIT_METHOD`, `SASE_PR_NAME`, `SASE_PR_STATUS`, and `SASE_BUG_ID`. Use
`gh` only for GitHub API/PR reads when needed.

Typical project-task prompt: `#gh:sase %auto #pr:my_change <task text>`.
