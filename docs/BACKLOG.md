# GlassHood-Azure — Backlog

## REQ-GHA-001: "Sign in with Microsoft" (Entra ID) SSO, above Google
- **Goal:** A *working* Microsoft/Entra ID login button on the demo login screen, positioned above the existing Google corporate SSO. Real federation — never a dead button.
- **Sizing (neo, verified against the code — EASY):** SSO is **Auth0-brokered**; the backend `verify_token` validates Auth0 tokens regardless of upstream IdP (provider-agnostic). Frontend uses `@auth0/auth0-react`. So:
  - Add a Microsoft/Entra Enterprise (or social) connection in the Auth0 tenant `your-tenant.us.auth0.com` + an Entra app registration → ~30 min (needs Auth0 dashboard access; Entra app reg can be done via `az`).
  - Frontend: button calling `loginWithRedirect({ connection: '<entra-conn>' })` above Google in `LoginScreen.jsx` → ~15 min, **no backend change**.
  - Add the demo callback URL to the Auth0 app's Allowed Callback URLs.
- **Dependency:** Auth0 dashboard access (the connection lives there).
- **Honesty constraint:** label it "Sign in with Microsoft" (OIDC login only) — do not imply SCIM / conditional access that isn't built.
- **Status:** tracked, deferred (Igor 2026-06-13). Benefits prod GlassHood too (shared Auth0 + code).

## REQ-GHA-002: Externalize all deployment config out of code AND image (runtime-injected)
- **Goal:** The built image carries ZERO internal identifiers. Project IDs, org ID, MIG/instance names, log filters, endpoints, AND the topology manifest are supplied at runtime from Azure config / Key Vault (mounted), not hardcoded and not baked into the image.
- **Why (Igor 2026-06-13):** these are deployment config / effectively secrets — they should never be hardcoded. Doing it right makes the repo publishable as a *consequence*, and is the prerequisite for a clean attestation story (a generic attested image + injected config).
- **State:** code already reads via `getenv` (real values are Azure env vars). Remaining: the topology manifest is still baked into the image (`config/` COPYed in Dockerfile) — move to a runtime mount (Azure Files / Key Vault config blob) so the image is generic.
- **Status:** tracked, do before attestation.

## REQ-GHA-003: Azure code attestation (ColdVault-parity)
- **Goal:** Mirror ColdVault's GCP SEV-SNP attestation on Azure — a hardware-rooted attestation endpoint proving the workload runs in a genuine TEE.
- **Approach:** Container Apps has NO TEE — move the workload to **Azure Confidential Computing** (Confidential VM: AMD SEV-SNP / Intel TDX, or confidential container on ACI/AKS) + integrate **Microsoft Azure Attestation (MAA)**; expose an attestation endpoint returning the MAA token (parity with ColdVault REQ-073).
- **Why:** strong security-first signal for the Zurich / regulated-finance story; demonstrates cross-cloud confidential-compute competence.
- **Depends on:** REQ-GHA-002 (generic image). **Status:** Phase 2 (bigger lift — compute change + attestation integration).

## Publish runbook (clean-history flip — do NOT make public before this)
1. Finish all work in this private repo (history may be un-sanitized — fine while private).
2. SYNC with cypher: pull `architecture-site/` commits into the working tree.
3. Confirm the full tree is sanitized (no real identifiers in tracked files).
4. Collapse to a single sanitized commit (fresh history) → delete old repo → recreate same name → push the one commit.
5. cypher re-clones the new repo (old clone orphaned — history replaced). Coordinate timing (no mid-push).
6. THEN flip public. (Force-push alone is NOT enough — GitHub retains dangling commits by SHA; delete+recreate guarantees zero residual.)

## REQ-GHA-004: Guest entry = honest read-only view of the LIVE system (not "demo")
- **Goal:** Reframe the unauthenticated guest entry from "demo" to an honest read-only view of the *real, live* system. It IS live — guests just get read-only access, not full access.
  - Entry button: **"Read-only access"** (+ microcopy "Live production data · No login required · Server-side enforced") — no "demo" wording. (Label finalized via 9r multi-model debate 2026-06-14: access-tier framing pairs with sibling "Login (full access)"; both "demo" and "guest" rejected — "guest" is Azure-inaccurate (Entra B2B guest = an *authenticated* external user), "demo" implies fake data.)
  - Persistent in-app badge: **"Read-only · live system"** so guests understand it's the real system in a viewing capacity, not a mockup.
  - **Key requirement (makes the "live" label honest):** the guest entry must show the **live topology, read-only** — today it serves a static fixture, so point it at live data (read-only role / public read-only topology). Read-only must be enforced (no actions, no privileged drill-downs).
  - Route `/guest` or `/view` if low-cost; otherwise keep the path and fix visible text only.
- **Deferred sub-item (backlog — Igor OK to defer):** genericize the guest-view display labels (component / model / region identifiers) so the read-only view conveys the architecture without specific internal identifiers.
- **Owners:** neo (app — relabel, badge, live read-only routing, label genericization). cypher (portal — "Launch demo" button text → match, one line).
- **Status:** app IMPLEMENTED (:wif6, rev glasshood--0000005, live on glasshood.ai — guest button → "Read-only access" + microcopy "Live production data · No login required · Server-side enforced"; persistent "Read-only · live system" badge; all "demo" wording removed; live read-only enforced via viewer RBAC). Cypher portal rename PENDING (now → "Read-only access", not "View live (read-only)"). Display-label genericization still deferred.
