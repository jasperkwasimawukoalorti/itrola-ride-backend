"""
Auth utilities: OTP handling stub + JWT token issuance.
Ghana taxi apps typically use phone + OTP rather than passwords,
since many drivers won't reliably use email.
"""
import os
import random
import string
from datetime import datetime, timedelta
from jose import jwt

SECRET_KEY = os.getenv("JWT_SECRET", "change-this-in-production")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24 * 7  # 7 days, riders/drivers shouldn't re-login often


def generate_otp(length: int = 6) -> str:
    return "".join(random.choices(string.digits, k=length))


def create_access_token(subject: str, role: str) -> str:
    """subject = user id (rider or driver), role = 'rider' or 'driver'."""
    expire = datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    payload = {"sub": subject, "role": role, "exp": expire}
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)


def decode_access_token(token: str) -> dict:
    return jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])


# --- OTP SMS sending stub ---
def send_otp_sms(phone: str, otp: str):
    """
    Wire this up to an SMS gateway that works well in Ghana,
    e.g. Hubtel SMS API or Arkesel. For now this just logs.
    """
    print(f"[SMS STUB] Sending OTP {otp} to {phone}")
