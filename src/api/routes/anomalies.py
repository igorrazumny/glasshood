# File: src/api/routes/anomalies.py
# Purpose: GET /api/anomalies — current anomalies and baseline stats

from fastapi import APIRouter, Request

from src.api.routes.auth import verify_token
from src.security.anomaly_detector import get_anomalies, get_baseline_stats

router = APIRouter(tags=["anomalies"])


@router.get("/api/anomalies")
def list_anomalies(request: Request):
    """Return current detected anomalies with z-scores and confidence."""
    verify_token(request)
    anomalies = get_anomalies()
    return {
        "anomalies": anomalies,
        "count": len(anomalies),
        "critical_count": sum(1 for a in anomalies if a.get("severity") == "critical"),
    }


@router.get("/api/anomalies/baselines")
def baselines(request: Request):
    """Return current baseline stats for all tracked metrics (debugging)."""
    verify_token(request)
    return {"baselines": get_baseline_stats()}
