# architecture-site

Public architecture portal for GlassHood-on-Azure — served at `architecture.glasshood.ai`.

Static site (no database, no build step): plain HTML/CSS/JS under `public/`, using the
9robots design system. Diagrams are maintained as code (inline SVG) so they can't drift
from the real system.

## Boundaries
- This folder is self-contained. It does **not** touch the GlassHood application
  (`src/`, `frontend/`, `config/`, `Dockerfile`, `az-token.py`).
- All content uses **generic labels** — no project IDs, service-account names,
  endpoints, or other internal identifiers. Public architecture, zero sensitive internals.

## Deploy (Firebase Hosting)
```
cd architecture-site
firebase deploy --only hosting:portal --project nr-94n84ruwuw31-prod
```
`.firebaserc` (the hosting project id) is local-only and git-ignored; copy
`.firebaserc.example` to set it up on a new machine.

## Index gate
The portal is `noindex` (meta tag + `X-Robots-Tag` header + `robots.txt`) until the
deployment status is confirmed green. Flip those off to make it indexable.
