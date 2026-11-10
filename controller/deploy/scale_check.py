# File: controller/deploy/scale_check.py
# Purpose: REQ-GHA-018 third amendment — read the container app's JSON (stdin) for cutover.sh scale.
#   scale_check.py ready   exit 0 when provisioning Succeeded and the latest revision is the ready one
#   scale_check.py scale   exit 0 when the scale holds pollingInterval 1 and cooldownPeriod 30
import json
import sys


def ready(app: dict) -> bool:
    p = app.get("properties") or {}
    latest, ready_rev = p.get("latestRevisionName"), p.get("latestReadyRevisionName")
    return p.get("provisioningState") == "Succeeded" and bool(latest) and latest == ready_rev


def scale(app: dict) -> bool:
    s = ((app.get("properties") or {}).get("template") or {}).get("scale") or {}
    return s.get("pollingInterval") == 1 and s.get("cooldownPeriod") == 30


if __name__ == "__main__":
    check = {"ready": ready, "scale": scale}[sys.argv[1]]
    sys.exit(0 if check(json.load(sys.stdin)) else 1)
