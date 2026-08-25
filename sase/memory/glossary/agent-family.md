---
keyword: Agent Family
---

An agent family is a sase agent whose agent shells run as a strictly sequential chain.
Its shells use `<family>--<suffix>` names. The first `%id(parent, suffix)` attachment
renames the original shell with its own suffix and reserves the bare family name as the
sase agent container, so a family always has at least two shells.
