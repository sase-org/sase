---
plan: sdd/tales/202606/fix_vcs_project_completion_blank_line.md
---
 The `+` project completion LSP support that we recently added (see the sase-4z epic bead for context) results in a blank line being added above the VCS xprompt workflow when used at the start of the line. For example, assume the user types the following on this system:

```
+s<enter>
```

We would then expect the prompt to transform to

```
#gh:sase 
```

Instead, it expands to the following:

```

#gh:sase 
```

Can you help me diagnose the root cause of this issue and fix it? Think this through thoroughly and create a plan using your `/sase_plan` skill. Submit your plan with the
`sase plan propose` command (as the skill instructs) before making any file changes.
 