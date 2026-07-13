---
tags: [railway, deploy]
created: 2026-07-10
---

# Railway variables

Shared variables live on the environment, service variables on the service.
See [[Railway Gotchas]] for the full story, or [[Some Page|the alias note]].

![[deploy-diagram.png]]

## The gotcha

A shared variable referenced by a service is resolved at deploy time, not at
runtime — redeploy the service after changing the shared value.
