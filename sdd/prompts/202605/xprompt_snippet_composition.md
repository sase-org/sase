---
plan: sdd/tales/202605/xprompt_snippet_composition.md
---
 Can you help me add support for composing sase xprompt snippets? For example, consider the following snippets:

```
  baz:
    snippet: true
    content: "Don't forget to review bazbuz first!"
  foo:
    snippet: true
    content: "Can you help me foobar? #baz"
```

If the user were to then type `foo<tab>` in the prompt input widget, I would expect the text "Can you help me foobar?
Don't forget to review bazbuz first!" to expand. Think this through thoroughly and create a plan using your `/sase_plan` skill before making any file changes.
