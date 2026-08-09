"""
Phone + OTP auth flow. In-memory OTP store used here for simplicity —
swap for Redis in production so OTPs survive restarts and work across
multiple server instances.
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import generate_otp, send_otp_sms, create_access_token
from app.models.models import User, Driver
from app.schemas.schemas import OTPRequest, OTPVerify, TokenResponse

router = APIRouter(prefix="/auth", tags=["auth"])

# NOTE: replace with Redis (key=phone, value=otp, ttl=5min) in production
_otp_store: dict[str, str] = {}


@router.post("/request-otp")
def request_otp(payload: OTPRequest):
    otp = generate_otp()
    _otp_store[payload.phone] = otp
    send_otp_sms(payload.phone, otp)
    return {"message": "OTP sent"}


@router.post("/verify-otp", response_model=TokenResponse)
def verify_otp(payload: OTPVerify, db: Session = Depends(get_db)):
    expected = _otp_store.get(payload.phone)
    if expected is None or expected != payload.otp:
        raise HTTPException(status_code=400, detail="Invalid or expired OTP")

    del _otp_store[payload.phone]

    if payload.role == "rider":
        user = db.query(User).filter(User.phone == payload.phone).first()
        if not user:
            user = User(phone=payload.phone)
            db.add(user)
            db.commit()
            db.refresh(user)
        token = create_access_token(subject=user.id, role="rider")

    elif payload.role == "driver":
        driver = db.query(Driver).filter(Driver.phone == payload.phone).first()
        if not driver:
            raise HTTPException(
                status_code=404,
                detail="No driver account found. Complete onboarding first."
            )
        token = create_access_token(subject=driver.id, role="driver")

    else:
        raise HTTPException(status_code=400, detail="role must be 'rider' or 'driver'")

    return TokenResponse(access_token=token)
