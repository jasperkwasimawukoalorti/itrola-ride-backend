"""
Auth utilities: OTP handling stub + JWT token issuance.
Ghana taxi apps typically use phone + OTP rather than passwords,
since many drivers won't reliably use email.
"""
import os
import random
import string
import httpx
from pathlib import Path
from dotenv import load_dotenv
from datetime import datetime, timedelta
from jose import jwt

load_dotenv(dotenv_path=Path(__file__).resolve().parents[2] / ".env")

SECRET_KEY = os.getenv("JWT_SECRET", "change-this-in-production")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24 * 7  # 7 days, riders/drivers shouldn't re-login often

OTP_TTL_SECONDS = 5 * 60  # matches the "5min" comment in auth.py's docstring —
                           # that comment described the intent but nothing
                           # enforced it until auth.py's _otp_store started
                           # storing (otp, expires_at, attempts) tuples.

if SECRET_KEY == "change-this-in-production":
    # Loud on purpose. A silent fallback here means every JWT this process
    # issues is forgeable by anyone who reads this source file — which,
    # since itrola-ride-backend is a public repo, is anyone.
    print(
        "\n*** WARNING: JWT_SECRET is not set — using the insecure default. "
        "Tokens issued right now can be forged by anyone. Set JWT_SECRET in "
        ".env and make sure something actually loads it (see main.py). ***\n"
    )


def generate_otp(length: int = 6) -> str:
    return "".join(random.choices(string.digits, k=length))


def create_access_token(subject: str, role: str) -> str:
    """subject = user id (rider or driver), role = 'rider' or 'driver'."""
    expire = datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    payload = {"sub": subject, "role": role, "exp": expire}
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)


def decode_access_token(token: str) -> dict:
    return jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])


# --- OTP SMS sending ---
ARKESEL_API_KEY = os.getenv("ARKESEL_API_KEY", "")
ARKESEL_SENDER_ID = os.getenv("ARKESEL_SENDER_ID", "itrolaRide")
ARKESEL_URL = "https://sms.arkesel.com/api/v2/sms/send"


def send_otp_sms(phone: str, otp: str):
    """
    Sends via Arkesel (widely used for Ghanaian numbers) if ARKESEL_API_KEY
    is set in .env. Falls back to console logging if it isn't — so this
    keeps working exactly as before for local dev with zero setup, and
    switches to real delivery the moment you add a real API key. No code
    change needed to go live on this specific piece; just the env var.

    NOT YET TESTED against Arkesel's live API — same caveat as payments.py's
    Paystack integration. Verify with a real account and a real phone number
    before relying on this for actual users.
    """
    if not ARKESEL_API_KEY:
        print(f"[SMS STUB] Sending OTP {otp} to {phone}")
        return

    try:
        response = httpx.post(
            ARKESEL_URL,
            headers={"api-key": ARKESEL_API_KEY},
            json={
                "sender": ARKESEL_SENDER_ID,
                "message": f"Your itrola Ride verification code is {otp}. It expires in 5 minutes.",
                "recipients": [phone],
            },
            timeout=10.0,
        )
        if response.status_code >= 400:
            # Don't crash the OTP request over an SMS provider hiccup — log
            # loudly instead, since a silent failure here means the person
            # never gets their code and has no idea why.
            print(f"[SMS ERROR] Arkesel returned {response.status_code}: {response.text}")
    except httpx.RequestError as e:
        print(f"[SMS ERROR] Could not reach Arkesel: {e}")
