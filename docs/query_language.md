# Query Language Reference

The ChangeSpec query language filters ChangeSpecs using boolean expressions that combine
string matching, property filters, and operational shorthands. It is used by the PRs
sub-tab in `sase ace [query]` and by other ChangeSpec filters such as
`sase axe start --query`.

Normal query surfaces use enabled-project ChangeSpec discovery. Disabled projects are
omitted from CLI search and day-to-day ACE/axe scans. Views that are specifically about
agent history or old artifacts opt into all project lifecycle states explicitly.

This page documents ChangeSpec queries. The Agents tab in ACE has a separate agent query
language with agent-specific property keys.

## String Matching

Bare words and double-quoted strings perform case-insensitive substring matching against
all searchable fields. Use quoted strings when the value contains spaces, punctuation,
or other characters that are not valid in a bare word:

```
foobar           bare word, matches "FooBar", "FOOBAR", etc.
"foo bar"        quoted string, allows spaces and special characters
```

Prefix a quoted string with `c` to force case-sensitive matching:

```
c"FooBar"        matches only "FooBar", not "foobar" or "FOOBAR"
```

Inside quoted strings, the following escape sequences are recognized: `\\` (literal
backslash), `\"` (literal quote), `\n` (newline), `\r` (carriage return), and `\t`
(tab).

## Searchable Fields

String matches search across these ChangeSpec fields as one combined text corpus:

- **name** -- the ChangeSpec name
- **description** -- the ChangeSpec description text
- **status** -- the status text as stored on the ChangeSpec
- **project** -- project directory basename (derived from file path)
- **parent** -- parent ChangeSpec name (if set)
- **cl** -- PR identifier (if set)
- **commits** -- history entry notes and suffixes
- **hooks** -- hook display commands and status line suffixes
- **comments** -- reviewer names, file paths, and suffixes
- **mentors** -- mentor status line suffixes

For normalized status matching, prefer the `status:` property filter instead of a plain
string match. `status:` strips workspace suffixes and the legacy `READY TO MAIL` suffix
before comparing.

## Property Filters

Property filters match against a specific ChangeSpec field rather than performing a
full-text substring search. The supported property filters are exact and
case-insensitive:

```
status:WIP            match ChangeSpecs with base status "WIP"
project:myproject     match ChangeSpecs whose effective project name is "myproject"
ancestor:parent_cl    match if name or parent chain includes "parent_cl"
name:foo              match ChangeSpecs whose name is exactly "foo"
sibling:bar           match ChangeSpecs in the same sibling family as "bar"
```

Valid property keys: `status`, `project`, `ancestor`, `name`, and `sibling`. Values can
be bare words (alphanumeric, `_`, `-`) or quoted strings (e.g. `status:"in progress"`).

The `project:` filter uses the ProjectSpec's configured `PROJECT_NAME` when present and
valid; otherwise it falls back to the canonical project directory key. A configured name
replaces the directory key for this exact filter rather than adding a second alias.
`PROJECT_ALIASES` are not matched by `project:` or the `+` shorthand, and storage paths,
workspace lookup, and VCS operations continue using the canonical directory key.

### Property Shorthand Prefixes

| Shorthand    | Expands To           | Description                               |
| ------------ | -------------------- | ----------------------------------------- |
| `+myproject` | `project:myproject`  | Filter by project                         |
| `^parent_cl` | `ancestor:parent_cl` | Filter by ancestor (name or parent chain) |
| `~bar`       | `sibling:bar`        | Filter by sibling family                  |
| `&foo`       | `name:foo`           | Filter by exact name                      |

### Status Shorthands

| Shorthand | Expands To         |
| --------- | ------------------ |
| `%d`      | `status:DRAFT`     |
| `%m`      | `status:MAILED`    |
| `%r`      | `status:REVERTED`  |
| `%s`      | `status:SUBMITTED` |
| `%w`      | `status:WIP`       |
| `%y`      | `status:READY`     |

Status shorthands are case-insensitive (`%D` and `%d` are equivalent).

### Status Matching

The `status:` filter compares the base status only. For example, a ChangeSpec whose
stored status is `Ready (sase_102)` matches `status:Ready`. It also treats the legacy
`Ready - (!: READY TO MAIL)` form as base status `Ready`.

### Ancestor Matching

The `ancestor:` filter (and `^` shorthand) walks the parent chain recursively. A
ChangeSpec matches if its own name equals the value, or if any parent, grandparent, etc.
in the chain equals the value. Cycle detection prevents infinite loops.

### Sibling Matching

The `sibling:` filter (and `~` shorthand) strips any `__<N>` revert suffix from both the
search value and the ChangeSpec name, then compares base names. This matches all members
of a "family" -- the original plus its `__1`, `__2`, etc. variants.

## Boolean Operators

### AND (Implicit and Explicit)

Adjacent terms are combined with implicit AND. The `AND` keyword can also be used
explicitly:

```
feature test          implicit AND
feature AND test      explicit AND
```

### OR

The `OR` keyword combines alternatives (lower precedence than AND):

```
feature OR bugfix
```

### NOT

The `!` operator or `NOT` keyword negates the following expression:

```
!draft                exclude ChangeSpecs containing "draft"
NOT draft             same as above
!"work in progress"   negate a quoted string
```

Multiple `!` operators stack (double negation cancels out).

### Precedence

From tightest to loosest binding:

1. `!` / `NOT` (unary negation)
2. `AND` (explicit or implicit juxtaposition)
3. `OR`

Parentheses override precedence:

```
(feature OR bugfix) AND !skip
feature AND (test OR lint)
```

## Special Shorthands

These shorthands filter ChangeSpecs by error, agent, or process state recorded in status
or suffix fields.

### Error Suffix

| Syntax | Meaning                                                                            |
| ------ | ---------------------------------------------------------------------------------- |
| `!!!`  | Match ChangeSpecs that have an error suffix in status, commits, hooks, or comments |
| `!`    | Same as `!!!` when standalone: followed by whitespace or at end                    |
| `!!`   | Match ChangeSpecs with no error suffix (equivalent to `NOT !!!`; standalone only)  |

### Running Agents

| Syntax | Meaning                                                                      |
| ------ | ---------------------------------------------------------------------------- |
| `@@@`  | Match ChangeSpecs with a running agent marker in hooks, comments, or mentors |
| `@`    | Same as `@@@` when standalone                                                |
| `!@`   | Match ChangeSpecs with no running agents (equivalent to `NOT @@@`)           |

### Running Processes

| Syntax | Meaning                                                               |
| ------ | --------------------------------------------------------------------- |
| `$$$`  | Match ChangeSpecs with a running process marker in hooks or comments  |
| `$`    | Same as `$$$` when standalone                                         |
| `!$`   | Match ChangeSpecs with no running processes (equivalent to `NOT $$$`) |

### Any Special

| Syntax | Meaning                                                           |
| ------ | ----------------------------------------------------------------- |
| `*`    | Errors OR agents OR processes (equivalent to `!!! OR @@@ OR $$$`) |

Note: `!`, `@`, `$`, `!!`, `!@`, `!$`, and `*` are only treated as special shorthands
when standalone (at end of input or followed by whitespace). When `!` is followed by
other characters, as in `!"foo"`, it acts as the `NOT` operator.

## Practical Examples

```
%w                           all WIP ChangeSpecs
%w +myproject                WIP ChangeSpecs in "myproject"
feature %d                   drafted ChangeSpecs containing "feature"
!!! %m                       mailed ChangeSpecs with errors
!! !@ !$                     no errors, no agents, no processes
^base_cl %w                  WIP descendants of "base_cl"
~my_cl                       all siblings of "my_cl" (including reverted variants)
"fix bug" OR "refactor"      ChangeSpecs matching either phrase
(bug OR fix) AND !test       bug/fix ChangeSpecs excluding test ones
c"README" +docs              case-sensitive "README" in the docs project
*                            anything with errors, agents, or processes
```
