#!/usr/bin/env python3
# File: controller/deploy/fence.py
# Purpose: REQ-GHA-018 clause 13 — the cutover's view of the controller's state, as the
# logged-in az user (needs azure-identity, azure-data-tables, azure-storage-queue, httpx).
#   fence.py pin                 rollback: awake and pinned (never sleeps), epoch bumped
#   fence.py unpin               enable: the app may sleep again
#   fence.py wait                wait out the operation a reconciler may have left with Azure
#   fence.py halt | resume       last resort: stop every reconciler (nothing repairs) / allow again
#   fence.py intent              {"desired", "generation", "settled", "pinned", "halted"}
#   fence.py has-message <gen>   exit 0 if a wake message of that generation is seen
# Settings from the environment: SA, CONTAINER_APP_ID, CONTAINER_APP_FQDN.
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from azure.data.tables import TableServiceClient  # noqa: E402
from azure.identity import AzureCliCredential  # noqa: E402
from azure.storage.queue import QueueClient  # noqa: E402

from wake import fence  # noqa: E402
from wake.state import TableStore, control_of, intent_of  # noqa: E402

SA = os.environ.get("SA", "stghcfgc6c91c0a")
cred = AzureCliCredential()
store = TableStore(TableServiceClient(f"https://{SA}.table.core.windows.net", credential=cred))


def queue():
    return QueueClient(f"https://{SA}.queue.core.windows.net", "glasshood-wake", credential=cred)


def main(cmd: str, args: list[str]) -> int:
    if cmd == "pin":
        import time
        fence.pin(store, time.time())
    elif cmd == "unpin":
        import time
        fence.unpin(store, time.time())
    elif cmd == "halt":
        print(json.dumps(fence.halt(store)))
    elif cmd == "resume":
        print(json.dumps(fence.resume(store)))
    elif cmd == "wait":
        from wake.azure_ops import AzureOps
        ops = AzureOps(cred, os.environ["CONTAINER_APP_ID"], os.environ["CONTAINER_APP_FQDN"], queue())
        print(json.dumps(fence.wait_pending(store, ops)))
    elif cmd == "intent":
        entity = store.read()[0]
        i, c = intent_of(entity), control_of(entity)
        print(json.dumps({"desired": i.desired, "generation": i.generation,
                          "settled": i.settled, "pinned": i.pinned, "halted": c["halted"]}))
    elif cmd == "has-message":
        # Verification only (Peek shows visible messages; the caller retries while a
        # scan has them briefly invisible). Decisions never rely on Peek.
        g = int(args[0])
        gens = [json.loads(m.content).get("generation") for m in queue().peek_messages(max_messages=32)]
        return 0 if g in gens else 1
    else:
        print(__doc__ or "usage: fence.py halt|wait|resume|intent|has-message <gen>", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else "", sys.argv[2:]))
