# GlassHood wake controller (REQ-GHA-018)

The controller decides when the GlassHood app is awake. It runs as one small Azure Functions app (Flex Consumption, Python).

- **Endpoints.** They only record what is wanted (the *intent*) in one Table entity.
  - `GET /api/status` (public): `{state: asleep|waking|awake|going-to-sleep, since, expected_seconds}`.
  - `POST /api/wake` (public): needs a reCAPTCHA v3 token, or the current wake's use token. Answers `202 {use_token, use_token_expires}`.
  - `POST /api/use` (public): needs the current wake's use token. Records person-caused use.
  - Operator endpoints (function key): `POST /api/ops/wake`, `POST /api/ops/sleep`, `POST /api/ops/hold?hours=N`, `GET /api/ops/status`.
- **Reconciler** (`wake/reconciler.py`). It is the only code that changes Azure. It runs every minute and on demand. It holds a blob lease and bumps the epoch each time it takes over. It finishes any pending operation before acting. It then takes one step at a time toward the newest intent (`wake/core.py`) and records every event in a second table.
- **Asleep.** The wake queue is empty and ingress is restricted to `127.0.0.1/32`, so outside requests get 403 and wake nothing.
- **Awake.** The wake queue holds one current-generation message, so the queue scale rule keeps one replica running, and ingress is open.

Design: the REQ-GHA-018 design v6 thread (peer proceed 2026-10-18). Requirement: `docs/BACKLOG.md` REQ-GHA-018.

## Operating

| Command | Purpose |
|---|---|
| `controller/deploy/setup.sh` | Creates or updates the controller's Azure pieces. Needs `RECAPTCHA_SECRET` in the environment. It leaves the reconciler **off**: `RECONCILE=off`, and `/status` says `awake`. |
| `controller/deploy/budget.sh` | Sets the CHF 10/month forecast and actual alert. Needs `TO=<email>`. |
| `controller/deploy/ops.sh status\|wake\|sleep\|hold <hours>` | Operator commands. All are safe to repeat. |

Nothing changes the live app until the cutover (clause 13 step e) sets `RECONCILE=on`. The cutover also gives the app its queue scale rule (min 0 / max 1, cooldown 30 s) and its 120 s termination grace.

## Tests

```
cd controller && python -m pytest -q tests
```
