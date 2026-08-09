"""
Trip request -> nearest-driver match -> lifecycle transitions.

Matching uses a straightforward PostGIS nearest-neighbor query. This is
fine until you have thousands of concurrent drivers; no need for
geohash/H3 sharding at MVP scale.

Auth model:
- /request requires a rider JWT; rider_id comes from the token, never from
  client input, so a rider can only ever book trips for themselves.
- /start and /complete require the assigned driver's own JWT.
- /cancel allows either the trip's rider or its driver.
- GET /{trip_id} allows either party on the trip.
"""
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import text
from geoalchemy2.shape import from_shape
from shapely.geometry import Point

from app.core.database import get_db
from app.core.deps import require_rider, require_driver, get_current_user, CurrentUser
from app.models.models import Trip, Driver, DriverLocation, TripStatus, DriverStatus
from app.schemas.schemas import TripRequest, TripOut

router = APIRouter(prefix="/trips", tags=["trips"])

BASE_FARE = 10.0       # GHS, adjust to your market
PER_KM_RATE = 2.5      # GHS per km, placeholder — validate against local rates


def estimate_fare(distance_km: float) -> float:
    return round(BASE_FARE + distance_km * PER_KM_RATE, 2)


@router.post("/request", response_model=TripOut)
def request_trip(
    payload: TripRequest,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(require_rider),
):
    pickup = from_shape(Point(payload.pickup_lng, payload.pickup_lat), srid=4326)
    dropoff = from_shape(Point(payload.dropoff_lng, payload.dropoff_lat), srid=4326)

    # Rough straight-line distance for fare estimate.
    # Swap for Google Distance Matrix API for accurate road distance.
    result = db.execute(
        text("SELECT ST_Distance(:p1, :p2) / 1000.0"),
        {"p1": str(pickup), "p2": str(dropoff)}
    ).scalar()
    distance_km = result or 1.0

    trip = Trip(
        rider_id=current_user.id,
        pickup_location=pickup,
        dropoff_location=dropoff,
        status=TripStatus.requested,
        fare_estimate=estimate_fare(distance_km),
    )
    db.add(trip)
    db.commit()
    db.refresh(trip)

    # Attempt immediate match
    _try_match_driver(trip, db)

    return trip


def _try_match_driver(trip: Trip, db: Session):
    """Find nearest verified, available driver within 5km and assign them."""
    nearest = db.execute(
        text("""
            SELECT d.id
            FROM drivers d
            JOIN driver_locations dl ON dl.driver_id = d.id
            WHERE d.status = :verified
              AND d.is_available = true
              AND ST_DWithin(dl.location, :pickup, 5000)
            ORDER BY ST_Distance(dl.location, :pickup) ASC
            LIMIT 1
        """),
        {"verified": DriverStatus.verified.value, "pickup": str(trip.pickup_location)}
    ).first()

    if nearest:
        driver_id = nearest[0]
        trip.driver_id = driver_id
        trip.status = TripStatus.matched
        trip.matched_at = datetime.utcnow()

        driver = db.query(Driver).filter(Driver.id == driver_id).first()
        driver.is_available = False

        db.commit()


@router.post("/{trip_id}/start")
def start_trip(
    trip_id: str,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(require_driver),
):
    trip = _get_trip_or_404(trip_id, db)
    if trip.driver_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not the assigned driver for this trip")
    if trip.status != TripStatus.matched:
        raise HTTPException(status_code=400, detail=f"Cannot start trip from status {trip.status.value}")
    trip.status = TripStatus.in_progress
    trip.started_at = datetime.utcnow()
    db.commit()
    return {"message": "Trip started"}


@router.post("/{trip_id}/complete")
def complete_trip(
    trip_id: str,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(require_driver),
):
    trip = _get_trip_or_404(trip_id, db)
    if trip.driver_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not the assigned driver for this trip")
    if trip.status != TripStatus.in_progress:
        raise HTTPException(status_code=400, detail=f"Cannot complete trip from status {trip.status.value}")

    trip.status = TripStatus.completed
    trip.completed_at = datetime.utcnow()
    trip.fare_final = trip.fare_estimate  # replace with metered/actual distance calc

    driver = db.query(Driver).filter(Driver.id == trip.driver_id).first()
    if driver:
        driver.is_available = True

    db.commit()
    return {"message": "Trip completed", "fare_final": trip.fare_final}


@router.post("/{trip_id}/cancel")
def cancel_trip(
    trip_id: str,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
):
    trip = _get_trip_or_404(trip_id, db)
    _ensure_party_to_trip(trip, current_user)

    if trip.status in (TripStatus.completed, TripStatus.cancelled):
        raise HTTPException(status_code=400, detail="Trip already finished")

    trip.status = TripStatus.cancelled

    if trip.driver_id:
        driver = db.query(Driver).filter(Driver.id == trip.driver_id).first()
        if driver:
            driver.is_available = True

    db.commit()
    return {"message": "Trip cancelled"}


@router.get("/{trip_id}", response_model=TripOut)
def get_trip(
    trip_id: str,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
):
    trip = _get_trip_or_404(trip_id, db)
    _ensure_party_to_trip(trip, current_user)
    return trip


def _get_trip_or_404(trip_id: str, db: Session) -> Trip:
    trip = db.query(Trip).filter(Trip.id == trip_id).first()
    if not trip:
        raise HTTPException(status_code=404, detail="Trip not found")
    return trip


def _ensure_party_to_trip(trip: Trip, current_user: CurrentUser):
    """Only the trip's rider or assigned driver may view/cancel it."""
    is_rider = current_user.role == "rider" and current_user.id == trip.rider_id
    is_driver = current_user.role == "driver" and current_user.id == trip.driver_id
    if not (is_rider or is_driver):
        raise HTTPException(status_code=403, detail="Not a party to this trip")
