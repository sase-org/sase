---
keyword: Macro Invocation
aliases:
  - smack
  - macro reference
  - macro ref
---

A macro invocation (smack) is one `#name` or `#!name` use of a macro in prompt text,
with its arguments and modifiers: `#review(path=a)`, `#review:x`, `#review: text`,
`#flag+`, `#ns/name`, or a standalone `#!sync`. SASE expands or runs it before the agent
sees the prompt. The macro is the definition and the invocation is one use of it; a
prompt can hold zero or many. VCS workspace references such as `#gh:sase` and
`#git:home` are invocations of workspace workflows, and a project tag expands into one.
A `#` token that names no macro passes through as literal text, and one inside a literal
zone is not an invocation. Smack is short for sase macro invocation.
