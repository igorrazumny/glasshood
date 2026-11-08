# File: src/api/routes/preferences.py
# Purpose: REQ-GHA-046 clauses 15 and 16: where a signed-in user left the right-hand column's boundary.
#   Writes need an operator (app-wide gate, REQ-GHA-043), so the Live demo stores nothing.

import json
import os
import tempfile
import threading

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from src.api.routes.auth import verify_token

router = APIRouter()
_lock = threading.Lock()


class Split(BaseModel):
    split: float


def _file():
    d = os.getenv("AI_STATE_DIR", "")
    return os.path.join(d, "ui_prefs.json") if d else None


def _read() -> dict:
    path = _file()
    try:
        with open(path) as f:
            return json.load(f)
    except (TypeError, OSError, ValueError):
        return {}


@router.get("/api/preferences/right-panel")
def get_split(request: Request):
    user = verify_token(request)["user"]
    return {"split": _read().get(user, {}).get("split")}


@router.put("/api/preferences/right-panel")
def put_split(body: Split, request: Request):
    user = verify_token(request)["user"]
    if not 0.1 <= body.split <= 0.9:
        raise HTTPException(status_code=422, detail="split out of range")
    path = _file()
    if not path:
        raise HTTPException(status_code=503, detail="no folder is set up to keep preferences")
    with _lock:
        data = _read()
        data[user] = {"split": body.split}
        fd, tmp = tempfile.mkstemp(prefix=".ui_prefs.", dir=os.path.dirname(path))
        with os.fdopen(fd, "w") as f:
            json.dump(data, f)
        os.replace(tmp, path)
    return {"split": body.split}
