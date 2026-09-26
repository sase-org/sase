---
keyword: Named Proc
---

A named proc is a supervised proc with a stable `proc_name` (`proc_role: "proc"`), with
durable output and lifecycle state. A monitor turn's command runs as a named proc named
after its member. A stand-alone `%proc` xprompt unit is a named proc that belongs to no
agent or session, allocates no agent runner, and appears in the Agents tab as its own
proc node, counted separately from agents. A gate turn's execution proc
(`proc_role: "gate"`) does not make the gate turn a monitor turn. Formerly called a proc
shell.
