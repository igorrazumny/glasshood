# GlassHood wake controller (REQ-GHA-018)

The controller decides when the GlassHood app is awake. It runs as one small Azure Functions app (Flex Consumption, Python).

- **Endpoints.** They only record what is wanted (the *intent*) in one Table entity.
  - `GET /api/status` (public): `{state: asleep|waking|awake|going-to-sleep, since, expected_seconds}`.
  - `POST /api/wake` (public): needs a reCAPTCHA v3 token, or the current wake's use token. Answers `202 {use_token, use_token_expires}`.
  - `POST /api/use` (public): needs the current wake's use token. Records person-caused use.
  - Operator endpoints (function key): `POST /api/ops/wake`, `POST /api/ops/sleep`, `POST /api/ops/hold?hours=N`, `GET /api/ops/status`.
- **Reconciler** (`wake/reconciler.py`). It is the only code that changes Azure. It runs every minute and on demand. It holds a blob lease and bumps the epoch each time it takes over. It finishes any pending operation before acting (only `Succeeded`, `Failed` and `Canceled` are final; every other status is still pending). It then takes one step at a time toward the newest intent (`wake/core.py`) and records every event in a second table.
- **Queue scans.** Every decision about the wake queue comes from a fresh-receipt scan: Get Messages, re-read the intent, then delete or re-show each message once with the receipt just returned. Peek is never used. Asleep counts as empty only after clean scans have found nothing for longer than one visibility timeout.
- **Wake budget.** A wake not awake by its deadline (3 minutes, extended only by a genuinely slow Azure operation) fails and returns to asleep, however its steps failed.
- **Asleep.** The wake queue is empty and ingress is restricted to `127.0.0.1/32`, so outside requests get 403 and wake nothing.
- **Awake.** The wake queue holds one current-generation message, so the queue scale rule keeps one replica running, and ingress is open.

Design: the REQ-GHA-018 design v6 thread (peer proceed 2026-10-18). Requirement: `docs/BACKLOG.md` REQ-GHA-018.

## Operating

| Command | Purpose |
|---|---|
| `controller/deploy/setup.sh` | Creates or updates the controller's Azure pieces. Needs `RECAPTCHA_SECRET` in the environment. It leaves the reconciler **off**: `RECONCILE=off`, and `/status` says `awake`. |
| `controller/deploy/budget.sh` | Sets the CHF 10/month forecast and actual alert. Needs `TO=<email>`. |
| `controller/deploy/ops.sh status\|wake\|sleep\|hold <hours>` | Operator commands. All are safe to repeat. |

Gates for the cutover that fake tests cannot show (design v6, peer review 2026-10-18):

- The controller's identity can read real ARM operation-status URLs (`GlassHood wake operation reader`, from `setup.sh`): one accepted operation is followed to `Succeeded`.
- Failure reports reach the operator: `ACS_EMAIL_ENDPOINT`, `ALERT_EMAIL_FROM` and `ALERT_EMAIL_TO` are set and one test report arrives. Until then a failure is only an error log.
- Real image startup, ordinary and hung-request drain, Envoy stream survival, lease and late-write recovery, rollback, and the whole estate's cost.

Nothing changes the live app until the cutover (clause 13 step e) sets `RECONCILE=on`. The cutover also gives the app its queue scale rule (min 0 / max 1, cooldown 30 s) and its 120 s termination grace.

## Tests

```
cd controller && python -m pytest -q tests
```
