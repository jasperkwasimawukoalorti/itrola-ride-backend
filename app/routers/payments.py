"""
Paystack MoMo payment integration.

Flow:
1. Rider calls POST /trips/{trip_id}/pay with their MoMo number + network.
   We call Paystack's mobile_money charge endpoint, store the returned
   reference on the trip, and return the response (Paystack will trigger
   a MoMo prompt on the rider's phone for them to approve).
2. Paystack calls our webhook (POST /webhooks/paystack) when the charge
   settles. We verify the signature, look up the trip by reference, and
   update payment_status accordingly.

NOTE: This has NOT been tested against Paystack's live API — the sandbox
this was built in has no network access to api.paystack.co. The webhook
signature verification and trip status update logic HAVE been tested with
simulated webhook payloads. Test the actual charge call with your real
Paystack test-mode keys before going live.
"""
import os
import hmac
import hashlib
import httpx
from fastapi import APIRouter, Depends, HTTPException, Request, Header
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.deps import require_rider, CurrentUser
from app.models.models import Trip, TripStatus, PaymentStatus, PaymentMethod
from app.schemas.schemas import MoMoChargeRequest

router = APIRouter(tags=["payments"])

PAYSTACK_SECRET_KEY = os.getenv("PAYSTACK_SECRET_KEY", "")
PAYSTACK_BASE_URL = "https://api.paystack.co"

# Paystack's mobile_money channel expects a network provider code.
MOMO_PROVIDER_MAP = {
    "mtn": "mtn",
    "vodafone": "vod",
    "airteltigo": "atl",
}


@router.post("/trips/{trip_id}/pay")
async def initiate_momo_payment(
    trip_id: str,
    payload: MoMoChargeRequest,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(require_rider),
):
    trip = db.query(Trip).filter(Trip.id == trip_id).first()
    if not trip:
        raise HTTPException(status_code=404, detail="Trip not found")
    if trip.rider_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not your trip")
    if trip.status != TripStatus.completed:
        raise HTTPException(status_code=400, detail="Trip must be completed before payment")
    if trip.payment_status == PaymentStatus.paid:
        raise HTTPException(status_code=400, detail="Trip already paid")
    if not PAYSTACK_SECRET_KEY:
        raise HTTPException(status_code=500, detail="Payment provider not configured (PAYSTACK_SECRET_KEY missing)")

    provider = MOMO_PROVIDER_MAP.get(payload.network.lower())
    if not provider:
        raise HTTPException(status_code=400, detail="network must be one of: mtn, vodafone, airteltigo")

    amount_pesewas = int(round((trip.fare_final or trip.fare_estimate) * 100))

    async with httpx.AsyncClient(timeout=15.0) as client:
        try:
            resp = await client.post(
                f"{PAYSTACK_BASE_URL}/charge",
                headers={"Authorization": f"Bearer {PAYSTACK_SECRET_KEY}"},
                json={
                    "amount": amount_pesewas,
                    "email": f"{payload.momo_number}@itrolaride.placeholder",  # Paystack requires an email field
                    "currency": "GHS",
                    "mobile_money": {
                        "phone": payload.momo_number,
                        "provider": provider,
                    },
                },
            )
        except httpx.RequestError as e:
            raise HTTPException(status_code=502, detail=f"Could not reach payment provider: {e}")

    try:
        data = resp.json()
    except ValueError:
        raise HTTPException(
            status_code=502,
            detail=f"Payment provider returned a non-JSON response (HTTP {resp.status_code}). "
                   f"This can happen during a provider outage or if the API endpoint/network is misconfigured.",
        )

    if not data.get("status"):
        raise HTTPException(status_code=502, detail=data.get("message", "Payment initiation failed"))

    reference = data["data"]["reference"]
    trip.payment_method = PaymentMethod.momo
    trip.payment_reference = reference
    trip.payment_status = PaymentStatus.pending
    db.commit()

    return {
        "message": "MoMo prompt sent to rider's phone. Approve on your device to complete payment.",
        "reference": reference,
        "paystack_status": data["data"].get("status"),
    }


@router.post("/webhooks/paystack")
async def paystack_webhook(request: Request, x_paystack_signature: str = Header(None)):
    """
    Paystack signs the raw request body with HMAC-SHA512 using your secret key.
    We must verify against the RAW bytes, not re-serialized JSON, or the
    signature check will fail.
    """
    raw_body = await request.body()

    if not PAYSTACK_SECRET_KEY:
        raise HTTPException(status_code=500, detail="Payment provider not configured")

    expected_signature = hmac.new(
        PAYSTACK_SECRET_KEY.encode("utf-8"), raw_body, hashlib.sha512
    ).hexdigest()

    if not x_paystack_signature or not hmac.compare_digest(expected_signature, x_paystack_signature):
        raise HTTPException(status_code=401, detail="Invalid webhook signature")

    payload = await request.json()
    event = payload.get("event")
    reference = payload.get("data", {}).get("reference")

    return _handle_webhook_event(event, reference, db=None)


def _handle_webhook_event(event: str, reference: str, db: Session):
    """
    Separated for testability — db session normally comes from a dependency,
    but webhook signature verification happens before we'd know the trip,
    so this helper is called with an explicit session in tests.
    """
    from app.core.database import SessionLocal

    if db is None:
        db = SessionLocal()
        close_after = True
    else:
        close_after = False

    try:
        trip = db.query(Trip).filter(Trip.payment_reference == reference).first()
        if not trip:
            return {"message": "No matching trip for this reference, ignoring"}

        if event == "charge.success":
            trip.payment_status = PaymentStatus.paid
        elif event == "charge.failed":
            trip.payment_status = PaymentStatus.failed
        # Other events (e.g. charge.dispute.create) intentionally ignored for MVP.

        db.commit()
        return {"message": "Webhook processed"}
    finally:
        if close_after:
            db.close()
