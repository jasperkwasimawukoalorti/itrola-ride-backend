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
from datetime import datetime, timedelta
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
import sqlalchemy
from geoalchemy2 import Geography  # type: ignore[import-not-found]
from geoalchemy2.elements import WKTElement  # type: ignore[import-not-found]

from app.core.database import get_db
from app.core.deps import (
    require_rider,
    require_driver,
    get_current_user as auth_get_current_user,
    CurrentUser,
)
from app.models.models import Trip, Driver, DriverLocation, TripStatus, DriverStatus
from app.schemas.schemas import TripRequest, TripOut

router = APIRouter(prefix="/trips", tags=["trips"])

BASE_FARE = 10.0       # GHS, adjust to your market
PER_KM_RATE = 2.5      # GHS per km, placeholder — validate against local rates


def get_current_user(
    current_user: CurrentUser = Depends(auth_get_current_user),
) -> CurrentUser:
    """Resolve and return the authenticated user for trip-party endpoints."""
    return current_user


def estimate_fare(distance_km: float) -> float:
    return round(BASE_FARE + distance_km * PER_KM_RATE, 2)


@router.post("/request", response_model=TripOut)
def request_trip(
    payload: TripRequest,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(require_rider),
):
    pickup = WKTElement(
        f"POINT({payload.pickup_lng} {payload.pickup_lat})",
        srid=4326,
    )
    dropoff = WKTElement(
        f"POINT({payload.dropoff_lng} {payload.dropoff_lat})",
        srid=4326,
    )

    # Rough straight-line distance for fare estimate.
    # Swap for Google Distance Matrix API for accurate road distance.
    result = db.execute(
        sqlalchemy.select(
            sqlalchemy.func.ST_Distance(
                sqlalchemy.cast(pickup, Geography),
                sqlalchemy.cast(dropoff, Geography),
            ) / 1000.0
        )
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


def _try_match_driver(trip: Trip, db: Session) -> bool:
    """
    Find nearest verified, available driver within 5km and assign them.
    Returns True if a match was made, False otherwise — the caller (either
    the initial /request call, or the periodic sweep below) uses this to
    know whether to keep retrying.
    """
    location = sqlalchemy.cast(DriverLocation.location, Geography)
    pickup = sqlalchemy.cast(trip.pickup_location, Geography)
    distance = sqlalchemy.func.ST_Distance(location, pickup)
    nearest = db.execute(
        sqlalchemy.select(Driver.id)
        .join(DriverLocation, DriverLocation.driver_id == Driver.id)
        .where(
            Driver.status == DriverStatus.verified,
            Driver.is_available.is_(True),
            sqlalchemy.func.ST_DWithin(location, pickup, 5000),
        )
        .order_by(distance)
        .limit(1)
    ).first()

    if not nearest:
        return False

    driver_id = nearest[0]
    trip.driver_id = driver_id
    trip.status = TripStatus.matched
    trip.matched_at = datetime.utcnow()

    driver = db.query(Driver).filter(Driver.id == driver_id).first()
    driver.is_available = False

    db.commit()
    return True


# How long a trip sits unmatched before the periodic sweep will retry it.
# Matched immediately means it's still worth trying once more shortly after
# the first attempt, but not so soon that we're hammering the DB for no
# reason — 15s balances "rider doesn't wait too long" against "don't spam
# ST_DWithin queries every second for every unmatched trip".
REMATCH_STALE_AFTER_SECONDS = 15


def retry_unmatched_trips(db: Session) -> int:
    """
    Sweeps trips stuck in 'requested' status (no driver was available/nearby
    at the moment they were created, and _try_match_driver only ever ran
    once, at creation time) and retries matching for each. Called on a
    timer from main.py's background task — see start_rematch_loop there.

    Without this, a rider whose request happened to miss every online
    driver by a few seconds would be stuck forever with no trip ever
    getting assigned, since nothing else in this file re-attempts matching
    after the initial /request call.
    """
    cutoff = datetime.utcnow() - timedelta(seconds=REMATCH_STALE_AFTER_SECONDS)
    stale_trips = (
        db.query(Trip)
        .filter(Trip.status == TripStatus.requested)
        .filter(Trip.requested_at <= cutoff)
        .all()
    )

    matched_count = 0
    for trip in stale_trips:
        if _try_match_driver(trip, db):
            matched_count += 1

    return matched_count


@router.post("/{trip_id}/start")
def start_trip(
    trip_id: str,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(require_driver),
):
    trip = _get_trip_or_404(trip_id, db)
    if trip.driver_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not the assigned driver for this trip")
    # A driver may start the ride either immediately after matching or after
    # marking that they are en route to the pickup point.
    if trip.status not in (TripStatus.matched, TripStatus.en_route):
        raise HTTPException(
            status_code=400,
            detail=f"Cannot start trip from status {trip.status.value}",
        )
    trip.status = TripStatus.in_progress
    trip.started_at = datetime.utcnow()
    db.commit()
    return {"message": "Trip started"}


@router.post("/{trip_id}/en-route")
def mark_trip_en_route(
    trip_id: str,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(require_driver),
):
    """Mark a matched trip as en route to the rider."""
    trip = _get_trip_or_404(trip_id, db)
    if trip.driver_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not the assigned driver for this trip")
    if trip.status != TripStatus.matched:
        raise HTTPException(
            status_code=400,
            detail=f"Cannot mark trip en route from status {trip.status.value}",
        )
    trip.status = TripStatus.en_route
    db.commit()
    return {"message": "Trip is en route"}


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

@router.get("/mine/current", response_model=TripOut)
def get_current_trip_for_driver(
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(require_driver),
):
    """Returns the driver's active trip (matched/in_progress), or 404."""
    trip = (
        db.query(Trip)
        .filter(Trip.driver_id == current_user.id)
        .filter(Trip.status.in_([TripStatus.matched, TripStatus.en_route, TripStatus.in_progress]))
        .order_by(Trip.requested_at.desc())
        .first()
    )
    if not trip:
        raise HTTPException(status_code=404, detail="No active trip")
    return trip

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
