from datetime import datetime
from typing import Optional
from pydantic import BaseModel


# --- Auth ---
class OTPRequest(BaseModel):
    phone: str

    def __str__(self) -> str:
        masked_phone = f"***{self.phone[-4:]}" if self.phone else "***"
        return f"OTPRequest(phone={masked_phone!r})"


class OTPVerify(BaseModel):
    phone: str
    otp: str
    role: str  # "rider" or "driver"

    def __str__(self) -> str:
        masked_phone = f"***{self.phone[-4:]}" if self.phone else "***"
        return f"OTPVerify(phone={masked_phone!r}, role={self.role!r})"


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user_id: str

    def __str__(self) -> str:
        return f"TokenResponse(token_type={self.token_type!r}, user_id={self.user_id!r})"


# --- Driver onboarding ---
class DriverCreate(BaseModel):
    phone: str
    name: str
    ghana_card_number: str
    license_number: str
    license_expiry: datetime
    profile_photo_url: str
    vehicle_plate_number: str
    vehicle_photo_url: Optional[str] = None

    def __str__(self) -> str:
        """Return a readable representation without exposing sensitive IDs."""
        masked_phone = f"***{self.phone[-4:]}" if self.phone else "***"
        return (
            f"DriverCreate(name={self.name!r}, phone={masked_phone!r}, "
            f"license_expiry={self.license_expiry.isoformat()!r})"
        )


class VehicleCreate(BaseModel):
    plate_number: str
    make_model: Optional[str] = None
    roadworthy_expiry: Optional[datetime] = None
    insurance_expiry: Optional[datetime] = None
    photo_url: Optional[str] = None

    def __str__(self) -> str:
        return f"VehicleCreate(plate_number={self.plate_number!r}, make_model={self.make_model!r})"


class VehicleOut(BaseModel):
    id: str
    plate_number: str
    make_model: Optional[str] = None
    roadworthy_expiry: Optional[datetime] = None
    insurance_expiry: Optional[datetime] = None
    photo_url: Optional[str] = None

    def __str__(self) -> str:
        return f"VehicleOut(id={self.id!r}, plate_number={self.plate_number!r})"

    class Config:
        from_attributes = True


class DriverOut(BaseModel):
    id: str
    phone: str
    name: Optional[str]
    status: str
    rating_avg: float
    profile_photo_url: Optional[str] = None

    def __str__(self) -> str:
        return f"DriverOut(id={self.id!r}, name={self.name!r}, status={self.status!r})"

    class Config:
        from_attributes = True


# --- Location ---
class LocationUpdate(BaseModel):
    lat: float
    lng: float
    heading: Optional[float] = None

    def __str__(self) -> str:
        return f"LocationUpdate(lat={self.lat!r}, lng={self.lng!r}, heading={self.heading!r})"


# --- Trips ---
class TripRequest(BaseModel):
    pickup_lat: float
    pickup_lng: float
    dropoff_lat: float
    dropoff_lng: float

    def __str__(self) -> str:
        return (
            f"TripRequest(pickup=({self.pickup_lat!r}, {self.pickup_lng!r}), "
            f"dropoff=({self.dropoff_lat!r}, {self.dropoff_lng!r}))"
        )


class TripOut(BaseModel):
    id: str
    status: str
    driver_id: Optional[str]
    fare_estimate: Optional[float]
    payment_status: Optional[str] = None
    payment_reference: Optional[str] = None
    payment_method: Optional[str] = None

    def __str__(self) -> str:
        return f"TripOut(id={self.id!r}, status={self.status!r}, driver_id={self.driver_id!r})"

    class Config:
        from_attributes = True


class RatingCreate(BaseModel):
    trip_id: str
    rated_by: str  # "rider" or "driver"
    score: int
    comment: Optional[str] = None

    def __str__(self) -> str:
        return f"RatingCreate(trip_id={self.trip_id!r}, rated_by={self.rated_by!r}, score={self.score!r})"


# --- Payments ---
class MoMoChargeRequest(BaseModel):
    momo_number: str
    network: str  # "mtn", "vodafone", or "airteltigo"

    def __str__(self) -> str:
        """Return a readable representation without exposing the full phone number."""
        masked_number = f"***{self.momo_number[-4:]}" if self.momo_number else "***"
        return f"MoMoChargeRequest(network={self.network!r}, momo_number={masked_number!r})"
