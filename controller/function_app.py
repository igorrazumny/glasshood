# File: controller/function_app.py
# Purpose: REQ-GHA-018 wake controller on Azure Functions (Flex Consumption, Python).
# Public:   GET /status, POST /wake, POST /use
# Operator: POST /ops/wake, /ops/sleep, /ops/hold?hours=N, GET /ops/status (function key)
# Reconciler: every minute (timer) and on demand (control queue "wake-control").
#
# Settings (app settings; secrets as Key Vault references):
#   STORAGE_ACCOUNT, CONTAINER_APP_ID, CONTAINER_APP_FQDN, ALLOWED_ORIGINS,
#   RECAPTCHA_HOSTS, RECAPTCHA_SECRET, USE_TOKEN_SECRET,
#   optional ACS_EMAIL_ENDPOINT, ALERT_EMAIL_FROM, ALERT_EMAIL_TO (failure reports)
#   RECONCILE=on  — the only switch that lets the controller change Azure. Anything
#                   else (the default) leaves the app exactly as it is; it is turned
#                   on at the cutover step (e), never before (clause 13).

import json
import logging
import os

import azure.functions as func
from azure.identity import DefaultAzureCredential

from wake.api import Api, Config
from wake.reconciler import Reconciler

app = func.FunctionApp()
_cred = DefaultAzureCredential()
_account = os.environ.get("STORAGE_ACCOUNT", "")
CONTROL_QUEUE = "wake-control"
WAKE_QUEUE = "glasshood-wake"
LEASE_CONTAINER, LEASE_BLOB = "wake", "reconciler-lease"


def _csv(name: str) -> set[str]:
    return {x.strip() for x in os.environ.get(name, "").split(",") if x.strip()}


def _store():
    from azure.data.tables import TableServiceClient
    from wake.state import TableStore
    return TableStore(TableServiceClient(f"https://{_account}.table.core.windows.net", credential=_cred))


def _queue(name: str):
    from azure.storage.queue import QueueClient
    return QueueClient(f"https://{_account}.queue.core.windows.net", name, credential=_cred)


def _kick() -> None:
    _queue(CONTROL_QUEUE).send_message("reconcile")


class _BlobLease:
    def __init__(self):
        from azure.storage.blob import BlobClient
        self._blob = BlobClient(f"https://{_account}.blob.core.windows.net", LEASE_CONTAINER, LEASE_BLOB,
                                credential=_cred)
        self._lease = None
        self._until = 0.0

    def acquire(self, seconds: int) -> bool:
        import time
        from azure.core.exceptions import HttpResponseError, ResourceNotFoundError
        try:
            self._lease = self._blob.acquire_lease(lease_duration=seconds)
        except ResourceNotFoundError:
            self._blob.upload_blob(b"", overwrite=False)
            return self.acquire(seconds)
        except HttpResponseError:
            return False             # held by another owner
        self._until = time.time() + seconds
        return True

    def renew(self) -> bool:
        import time
        from azure.core.exceptions import HttpResponseError
        try:
            self._lease.renew()
        except HttpResponseError:
            return False
        self._until = time.time() + 60
        return True

    def seconds_left(self) -> float:
        import time
        return self._until - time.time()

    def release(self) -> None:
        try:
            self._lease.release()
        except Exception:            # an expired lease needs no release
            pass


def _notify(kind: str, detail: dict) -> None:
    endpoint, to = os.environ.get("ACS_EMAIL_ENDPOINT"), os.environ.get("ALERT_EMAIL_TO")
    if not (endpoint and to and os.environ.get("ALERT_EMAIL_FROM")):
        # Never silent: without the email settings the failure is at least an error log.
        logging.error("failure report NOT sent (email not configured): %s %s", kind, json.dumps(detail))
        return
    try:
        from azure.communication.email import EmailClient
        EmailClient(endpoint, _cred).begin_send({
            "senderAddress": os.environ["ALERT_EMAIL_FROM"],
            "recipients": {"to": [{"address": to}]},
            "content": {"subject": f"GlassHood wake controller: {kind}",
                        "plainText": json.dumps(detail, indent=2)},
        })
    except Exception as e:           # a failed report is itself recorded by the caller's log
        logging.error("failure report not sent: %s", e)


def _reconcile() -> str:
    if os.environ.get("RECONCILE") != "on":
        return "off"
    from wake.azure_ops import AzureOps
    store = _store()
    ops = AzureOps(_cred, os.environ["CONTAINER_APP_ID"], os.environ["CONTAINER_APP_FQDN"], _queue(WAKE_QUEUE))
    try:
        return Reconciler(store, ops, _BlobLease(), notify=_notify).run()
    except Exception as e:           # Azure unavailable or unexpected: record, report, retry next tick
        detail = {"error": type(e).__name__, "message": str(e)[:2000]}
        try:
            store.record("reconcile_error", detail)
        finally:
            _notify("reconcile_error", detail)
        raise


def _api() -> Api:
    cfg = Config(
        token_secret=os.environ["USE_TOKEN_SECRET"].encode(),
        recaptcha_secret=os.environ["RECAPTCHA_SECRET"],
        allowed_origins=_csv("ALLOWED_ORIGINS"),
        recaptcha_hosts=_csv("RECAPTCHA_HOSTS"),
        always_on=os.environ.get("RECONCILE") != "on",
    )
    return Api(_store(), cfg, kick=_kick)


def _respond(reply) -> func.HttpResponse:
    headers = {"Cache-Control": "no-store"}
    if reply.body is None:
        return func.HttpResponse(status_code=reply.status, headers=headers)
    return func.HttpResponse(json.dumps(reply.body), status_code=reply.status,
                             mimetype="application/json", headers=headers)


def _json(req: func.HttpRequest) -> dict:
    try:
        body = req.get_json()
        return body if isinstance(body, dict) else {}
    except ValueError:
        return {}


@app.route(route="status", methods=["GET"], auth_level=func.AuthLevel.ANONYMOUS)
def status(req: func.HttpRequest) -> func.HttpResponse:
    return _respond(_api().status())


@app.route(route="wake", methods=["POST"], auth_level=func.AuthLevel.ANONYMOUS)
def wake(req: func.HttpRequest) -> func.HttpResponse:
    return _respond(_api().wake(_json(req), req.headers.get("Origin")))


@app.route(route="use", methods=["POST"], auth_level=func.AuthLevel.ANONYMOUS)
def use(req: func.HttpRequest) -> func.HttpResponse:
    return _respond(_api().use(_json(req), req.headers.get("Origin")))


@app.route(route="ops/wake", methods=["POST"], auth_level=func.AuthLevel.FUNCTION)
def ops_wake(req: func.HttpRequest) -> func.HttpResponse:
    return _respond(_api().operator_wake())


@app.route(route="ops/sleep", methods=["POST"], auth_level=func.AuthLevel.FUNCTION)
def ops_sleep(req: func.HttpRequest) -> func.HttpResponse:
    return _respond(_api().sleep())


@app.route(route="ops/hold", methods=["POST"], auth_level=func.AuthLevel.FUNCTION)
def ops_hold(req: func.HttpRequest) -> func.HttpResponse:
    try:
        hours = float(req.params.get("hours", ""))
    except ValueError:
        return func.HttpResponse("hours must be a number", status_code=400)
    return _respond(_api().hold(hours))


@app.route(route="ops/status", methods=["GET"], auth_level=func.AuthLevel.FUNCTION)
def ops_status(req: func.HttpRequest) -> func.HttpResponse:
    return _respond(_api().operator_status())


@app.timer_trigger(schedule="0 * * * * *", arg_name="timer", run_on_startup=False)
def reconcile_timer(timer: func.TimerRequest) -> None:
    logging.info("reconcile (timer): %s", _reconcile())


@app.queue_trigger(arg_name="msg", queue_name=CONTROL_QUEUE, connection="ControlQueue")
def reconcile_now(msg: func.QueueMessage) -> None:
    logging.info("reconcile (requested): %s", _reconcile())
