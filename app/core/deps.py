"""
Auth guards for FastAPI routes.

Two layers:
1. JWT bearer auth for riders/drivers — decodes token, exposes (subject_id, role).
2. Admin auth — separate static API key (X-Admin-Key header), NOT a JWT.
   Admin actions (verifying drivers, etc.) are rare and done by staff/scripts,
   so a rotating static key is simpler than building a full admin user system
   for MVP. Rotate ADMIN_API_KEY via env var; never commit it.
"""
import os
from fastapi import Depends, HTTPException, Header
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jose import JWTError

from app.core.security import decode_access_token

security_scheme = HTTPBearer()

ADMIN_API_KEY = os.getenv("ADMIN_API_KEY", "change-this-admin-key")


class CurrentUser:
    def __init__(self, id: str, role: str):
        self.id = id
        self.role = role


def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security_scheme),
) -> CurrentUser:
    """Decodes the bearer token. Raises 401 if invalid/expired."""
    token = credentials.credentials
    try:
        payload = decode_access_token(token)
    except JWTError:
        raise HTTPException(status_code=401, detail="Invalid or expired token")

    subject = payload.get("sub")
    role = payload.get("role")
    if not subject or role not in ("rider", "driver"):
        raise HTTPException(status_code=401, detail="Invalid token payload")

    return CurrentUser(id=subject, role=role)


def require_rider(current_user: CurrentUser = Depends(get_current_user)) -> CurrentUser:
    if current_user.role != "rider":
        raise HTTPException(status_code=403, detail="Rider account required")
    return current_user


def require_driver(current_user: CurrentUser = Depends(get_current_user)) -> CurrentUser:
    if current_user.role != "driver":
        raise HTTPException(status_code=403, detail="Driver account required")
    return current_user


def require_self_driver(driver_id: str, current_user: CurrentUser = Depends(require_driver)) -> CurrentUser:
    """Ensures the authenticated driver can only act on their own driver_id."""
    if current_user.id != driver_id:
        raise HTTPException(status_code=403, detail="Cannot act on another driver's account")
    return current_user


def require_admin(x_admin_key: str = Header(...)) -> None:
    """Static-key admin guard for staff-only endpoints (e.g. driver verification)."""
    if x_admin_key != ADMIN_API_KEY:
        raise HTTPException(status_code=403, detail="Invalid admin key")
