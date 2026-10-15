---
keyword: clan-wave
aliases: []
---

# Clan Wave

A clan wave is a dependency layer of direct members in one generation of an agent clan.
Wait-free members begin in wave 1; a member that waits on another member follows its
latest predecessor's wave. A wave is a layer, not a barrier, so later waves may start
while earlier work is still running.
