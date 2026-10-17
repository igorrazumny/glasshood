# glasshood.ai — the public site

The static site in front of the GlassHood app (REQ-GHA-018): Home, Architecture, Contact and
"Open app", which leads to app.glasshood.ai. Plain HTML, CSS and JavaScript; no build tools.

| Path | What it is |
|---|---|
| `public/` | The site as served at glasshood.ai |
| `../architecture/` | The architecture page. One set of files, served at glasshood.ai/architecture/ and at the root of architecture.glasshood.ai |
| `architecture/` | The architecture host's own config and 404 page |
| `build.sh` | Assembles `out/site` and `out/architecture` and refuses a build that would show an email address |
| `verify.sh` | Checks both hosts as served: the built bytes, `/demo` forwarding, 404s, revalidation |

`/demo`, `/view`, `?demo` and `?view`, the older addresses of the live demo, go to
app.glasshood.ai/demo.

The app's state (asleep, waking up, awake, going to sleep) is read from the wake controller by
`../architecture/app-state.js`; nothing is shown until its address is set there.

Deploys run from `.github/workflows/website.yml` on a push to main that touches the site or the
architecture page: build, upload to the two Azure Static Web Apps, verify. The pages and
their wording are a first draft.

Local preview: `bash website/build.sh`, then serve `website/out/site` with any static server.
