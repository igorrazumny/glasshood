# File: src/api/routes/customers.py
# Purpose: Customer management API endpoints

from fastapi import APIRouter, Request, HTTPException
from pydantic import BaseModel
from typing import Optional

from src.api.routes.auth import verify_token
from src.auth.rbac import require_role, require_customer
from src.customers import manager

router = APIRouter(tags=["customers"])


class CreateCustomerRequest(BaseModel):
    customer_id: str
    display_name: str
    tier: str = "standard"
    region: str = "europe-west1"
    contact_email: str = ""
    retention_days: int = 365


@router.get("/api/customers")
def list_customers(request: Request):
    """List customer configurations. Admins see all; scoped admins see own only."""
    ctx = verify_token(request) or {}
    require_role(request, "admin")
    customers = manager.list_customers()
    user_cid = ctx.get("customer_id", "")
    if user_cid:
        customers = [c for c in customers if c.get("customer_id") == user_cid]
    return {"customers": customers, "count": len(customers)}


@router.get("/api/customers/{customer_id}")
def get_customer(request: Request, customer_id: str):
    """Get a single customer configuration. Requires admin role."""
    verify_token(request)
    require_role(request, "admin")
    require_customer(request, customer_id)
    config = manager.get_customer(customer_id)
    if not config:
        raise HTTPException(status_code=404, detail=f"Customer '{customer_id}' not found")
    return config


@router.post("/api/customers", status_code=201)
def create_customer(request: Request, body: CreateCustomerRequest):
    """Create a new customer configuration. Requires admin role."""
    verify_token(request)
    require_role(request, "admin")
    config = body.model_dump()
    try:
        result = manager.create_customer(config)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return result


@router.delete("/api/customers/{customer_id}")
def delete_customer(request: Request, customer_id: str):
    """Delete a customer configuration. Requires admin role (super-admin only)."""
    verify_token(request)
    require_role(request, "admin")
    require_customer(request, customer_id)
    deleted = manager.delete_customer(customer_id)
    if not deleted:
        raise HTTPException(status_code=404, detail=f"Customer '{customer_id}' not found")
    return {"status": "deleted", "customer_id": customer_id}
