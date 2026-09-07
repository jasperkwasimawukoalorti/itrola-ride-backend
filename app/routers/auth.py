"""
Phone + OTP auth flow. In-memory OTP store used here for simplicity —
swap for Redis in production so OTPs survive restarts and work across
multiple server instances. This module's own workarounds (TTL, attempt
limits, per-phone cooldown) are stopgaps for that same reason: they only
work correctly on a single process. A second uvicorn instance behind a
load balancer would have its own separate store, and someone could bypass
the rate limit by hitting a different instance.
"""
import time

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import generate_otp, send_otp_sms, create_access_token, OTP_TTL_SECONDS
from app.models.models import User, Driver
from app.schemas.schemas import OTPRequest, OTPVerify, TokenResponse

router = APIRouter(prefix="/auth", tags=["auth"])

# NOTE: replace with Redis (key=phone, value=otp, ttl=5min) in production
# value: (otp, expires_at_unix, attempts_used)
_otp_store: dict[str, tuple[str, float, int]] = {}
_last_request_at: dict[str, float] = {}

MAX_VERIFY_ATTEMPTS = 5      # after this many wrong guesses, the OTP is dead
REQUEST_COOLDOWN_SECONDS = 30  # stops someone spamming SMS costs by hammering request-otp


@router.post("/request-otp")
def request_otp(payload: OTPRequest):
    now = time.time()
    last = _last_request_at.get(payload.phone)
    if last is not None and (now - last) < REQUEST_COOLDOWN_SECONDS:
        wait = int(REQUEST_COOLDOWN_SECONDS - (now - last))
        raise HTTPException(status_code=429, detail=f"Please wait {wait}s before requesting another code")

    otp = generate_otp()
    _otp_store[payload.phone] = (otp, now + OTP_TTL_SECONDS, 0)
    _last_request_at[payload.phone] = now
    send_otp_sms(payload.phone, otp)
    return {"message": "OTP sent"}


@router.post("/verify-otp", response_model=TokenResponse)
def verify_otp(payload: OTPVerify, db: Session = Depends(get_db)):
    entry = _otp_store.get(payload.phone)
    if entry is None:
        raise HTTPException(status_code=400, detail="Invalid or expired OTP")

    expected, expires_at, attempts = entry

    if time.time() > expires_at:
        del _otp_store[payload.phone]
        raise HTTPException(status_code=400, detail="Invalid or expired OTP")

    if attempts >= MAX_VERIFY_ATTEMPTS:
        del _otp_store[payload.phone]
        raise HTTPException(status_code=429, detail="Too many attempts. Please request a new code")

    if expected != payload.otp:
        _otp_store[payload.phone] = (expected, expires_at, attempts + 1)
        raise HTTPException(status_code=400, detail="Invalid or expired OTP")

    del _otp_store[payload.phone]

    if payload.role == "rider":
        user = db.query(User).filter(User.phone == payload.phone).first()

        if not user:
            user = User(phone=payload.phone)
            db.add(user)
            db.commit()
            db.refresh(user)

        user_id = str(user.id)
        token = create_access_token(
            subject=user.id,
            role="rider"
        )
    elif payload.role == "driver":
        driver = db.query(Driver).filter(Driver.phone == payload.phone).first()

        if not driver:
            raise HTTPException(
                status_code=404,
                detail="No driver account found. Complete onboarding first."
            )

        user_id = str(driver.id)
        token = create_access_token(
            subject=driver.id,
            role="driver"
        )
    else:
        raise HTTPException(
            status_code=400,
            detail="role must be 'rider' or 'driver'"
        )

    return TokenResponse(
        access_token=token,
        user_id=user_id
    )