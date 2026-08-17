from datetime import datetime
from typing import Optional
from pydantic import BaseModel


# --- Auth ---
class OTPRequest(BaseModel):
    phone: str


class OTPVerify(BaseModel):
    phone: str
    otp: str
    role: str  # "rider" or "driver"


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


# --- Driver onboarding ---
class DriverCreate(BaseModel):
    phone: str
    name: str
    ghana_card_number: str
    license_number: str
    license_expiry: datetime


class VehicleCreate(BaseModel):
    plate_number: str
    make_model: Optional[str] = None
    roadworthy_expiry: Optional[datetime] = None
    insurance_expiry: Optional[datetime] = None


class DriverOut(BaseModel):
    id: str
    phone: str
    name: Optional[str]
    status: str
    rating_avg: float

    class Config:
        from_attributes = True


# --- Location ---
class LocationUpdate(BaseModel):
    lat: float
    lng: float
    heading: Optional[float] = None


# --- Trips ---
class TripRequest(BaseModel):
    pickup_lat: float
    pickup_lng: float
    dropoff_lat: float
    dropoff_lng: float


class TripOut(BaseModel):
    id: str
    status: str
    driver_id: Optional[str]
    fare_estimate: Optional[float]
    payment_status: Optional[str] = None
    payment_reference: Optional[str] = None
    payment_method: Optional[str] = None

    class Config:
        from_attributes = True


class RatingCreate(BaseModel):
    trip_id: str
    rated_by: str  # "rider" or "driver"
    score: int
    comment: Optional[str] = None


# --- Payments ---
class MoMoChargeRequest(BaseModel):
    momo_number: str
    network: str  # "mtn", "vodafone", or "airteltigo"
