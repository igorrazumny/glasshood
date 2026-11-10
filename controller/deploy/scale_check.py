# File: controller/deploy/scale_check.py
# Purpose: REQ-GHA-018 third amendment — read the container app's JSON (stdin) for cutover.sh scale.
#   scale_check.py ready   exit 0 when provisioning Succeeded and the latest revision is the ready one
#   scale_check.py scale   exit 0 when the scale holds pollingInterval 1 and cooldownPeriod 30
#   scale_check.py probes  exit 0 when the container carries PROBES (REQ-GHA-051 amendment 1)
import json
import sys


def ready(app: dict) -> bool:
    p = app.get("properties") or {}
    latest, ready_rev = p.get("latestRevisionName"), p.get("latestReadyRevisionName")
    return p.get("provisioningState") == "Succeeded" and bool(latest) and latest == ready_rev


def scale(app: dict) -> bool:
    s = ((app.get("properties") or {}).get("template") or {}).get("scale") or {}
    return s.get("pollingInterval") == 1 and s.get("cooldownPeriod") == 30


# REQ-GHA-051 amendment 1: the start is checked every second, with a timeout long enough that
# the first check does not fail; up to 4 minutes to start. Readiness, which sends the traffic, is
# also checked every second (10 misses before a replica stops receiving traffic).
PROBES = [
    {"type": "Startup", "tcpSocket": {"port": 8080}, "initialDelaySeconds": 1, "periodSeconds": 1,
     "timeoutSeconds": 3, "failureThreshold": 240},
    {"type": "Readiness", "tcpSocket": {"port": 8080}, "periodSeconds": 1, "timeoutSeconds": 3,
     "failureThreshold": 10},
]


def probes(app: dict) -> bool:
    c = ((((app.get("properties") or {}).get("template") or {}).get("containers")) or [{}])[0]
    have = {p.get("type"): p for p in c.get("probes") or []}
    return all(all(have.get(w["type"], {}).get(k) == v for k, v in w.items()) for w in PROBES)


if __name__ == "__main__":
    check = {"ready": ready, "scale": scale, "probes": probes}[sys.argv[1]]
    sys.exit(0 if check(json.load(sys.stdin)) else 1)
