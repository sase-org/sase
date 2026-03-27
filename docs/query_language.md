# Query Language Reference

The `sase ace` query language filters ChangeSpecs using boolean expressions that combine string matching, property
filters, and special shorthands.

## String Matching

Bare words and double-quoted strings perform case-insensitive substring matching against all searchable fields:

```
foobar           bare word, matches "FooBar", "FOOBAR", etc.
"foo bar"        quoted string, allows spaces and special characters
```

Prefix a quoted string with `c` to force case-sensitive matching:

```
c"FooBar"        matches only "FooBar", not "foobar" or "FOOBAR"
```

Inside quoted strings, the following escape sequences are recognized: `\\` (literal backslash), `\"` (literal quote),
`\n` (newline), `\r` (carriage return), `\t` (tab).

## Searchable Fields

String matches search across these ChangeSpec fields (combined):

- **name** -- the ChangeSpec name
- **description** -- the ChangeSpec description text
- **status** -- base status string (e.g. "Draft", "WIP")
- **project** -- project directory basename (derived from file path)
- **parent** -- parent ChangeSpec name (if set)
- **cl** -- CL identifier (if set)
- **kickstart** -- kickstart value (if set)
- **commits** -- history entry notes and suffixes
- **hooks** -- hook display commands and status line suffixes
- **comments** -- reviewer names, file paths, and suffixes
- **mentors** -- mentor status line suffixes

## Property Filters

Property filters match against a specific ChangeSpec field (exact, case-insensitive) rather than performing a full-text
substring search.

```
status:WIP            match ChangeSpecs with base status "WIP"
project:myproject     match ChangeSpecs in the "myproject" project
ancestor:parent_cl    match if name or parent chain includes "parent_cl"
name:foo              match ChangeSpecs whose name is exactly "foo"
sibling:bar           match ChangeSpecs in the same sibling family as "bar"
```

Valid property keys: `status`, `project`, `ancestor`, `name`, `sibling`. Values can be bare words (alphanumeric, `_`,
`-`) or quoted strings (e.g. `status:"in progress"`).

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

### Ancestor Matching

The `ancestor:` filter (and `^` shorthand) walks the parent chain recursively. A ChangeSpec matches if its own name
equals the value, or if any parent, grandparent, etc. in the chain equals the value. Cycle detection prevents infinite
loops.

### Sibling Matching

The `sibling:` filter (and `~` shorthand) strips any `__<N>` revert suffix from both the search value and the ChangeSpec
name, then compares base names. This matches all members of a "family" -- the original plus its `__1`, `__2`, etc.
variants.

## Boolean Operators

### AND (Implicit and Explicit)

Adjacent terms are combined with implicit AND. The `AND` keyword can also be used explicitly:

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

These shorthands filter ChangeSpecs by error, agent, or process status.

### Error Suffix

| Syntax | Meaning                                                           |
| ------ | ----------------------------------------------------------------- |
| `!!!`  | Match ChangeSpecs that have any error suffix                      |
| `!`    | Same as `!!!` (when standalone: followed by whitespace or at end) |
| `!!`   | NO error suffix (equivalent to `NOT !!!`; standalone only)        |

### Running Agents

| Syntax | Meaning                                                      |
| ------ | ------------------------------------------------------------ |
| `@@@`  | Match ChangeSpecs with a running agent                       |
| `@`    | Same as `@@@` (when standalone)                              |
| `!@`   | NO running agents (equivalent to `NOT @@@`; standalone only) |

### Running Processes

| Syntax | Meaning                                                         |
| ------ | --------------------------------------------------------------- |
| `$$$`  | Match ChangeSpecs with a running process                        |
| `$`    | Same as `$$$` (when standalone)                                 |
| `!$`   | NO running processes (equivalent to `NOT $$$`; standalone only) |

### Any Special

| Syntax | Meaning                                                           |
| ------ | ----------------------------------------------------------------- |
| `*`    | Errors OR agents OR processes (equivalent to `!!! OR @@@ OR $$$`) |

Note: `!`, `@`, and `$` are only treated as special shorthands when standalone (at end of input or followed by
whitespace). When `!` is followed by other characters (e.g., `!"foo"`), it acts as the NOT operator.

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
