"""
Driver onboarding + live location updates.

MVP approach: driver signs up -> status defaults to 'pending' -> admin
manually flips to 'verified' after checking Ghana Card / license / vehicle
docs. Automated document verification can come later.

Auth model:
- /onboard is public (that's how a driver gets into the system in the first place)
- /vehicle (GET + POST), /location, /availability require the driver's own JWT (require_self_driver)
- /verify requires the admin key (require_admin)
"""
from typing import List

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from geoalchemy2.shape import from_shape
from shapely.geometry import Point

from app.core.database import get_db
from app.core.deps import require_self_driver, require_admin, CurrentUser
from app.models.models import Driver, Vehicle, DriverLocation, DriverStatus
from app.schemas.schemas import DriverCreate, VehicleCreate, VehicleOut, DriverOut, DriverAdminOut, LocationUpdate

router = APIRouter(prefix="/drivers", tags=["drivers"])


@router.post("/onboard", response_model=DriverOut)
def onboard_driver(payload: DriverCreate, db: Session = Depends(get_db)):
    existing = db.query(Driver).filter(Driver.phone == payload.phone).first()
    if existing:
        raise HTTPException(status_code=400, detail="Driver already registered")

    driver = Driver(
        phone=payload.phone,
        name=payload.name,
        ghana_card_number=payload.ghana_card_number,
        license_number=payload.license_number,
        license_expiry=payload.license_expiry,
        profile_photo_url=payload.profile_photo_url,
        status=DriverStatus.pending,  # admin must verify before driver can go online
    )
    db.add(driver)
    db.commit()
    db.refresh(driver)

    # Vehicle is created here rather than via the separate /vehicle endpoint
    # below, since that endpoint requires the driver's own JWT via
    # require_self_driver — and at this point in the flow the driver has no
    # token yet (no OTP/login has happened). Bundling it into the public
    # onboarding call avoids a chicken-and-egg auth problem.
    vehicle = Vehicle(
        driver_id=driver.id,
        plate_number=payload.vehicle_plate_number,
        photo_url=payload.vehicle_photo_url,
    )
    db.add(vehicle)
    db.commit()

    return driver


@router.post("/{driver_id}/vehicle", response_model=VehicleOut)
def add_vehicle(
    driver_id: str,
    payload: VehicleCreate,
    db: Session = Depends(get_db),
    _: CurrentUser = Depends(require_self_driver),
):
    """
    Upserts, doesn't just insert. Used both for a driver's first vehicle
    (right after onboarding, if it wasn't set during /onboard) and for
    later updates (new car, replacement photo, etc.) — same endpoint,
    same JWT-gated flow, no app rebuild needed for that second case since
    this only requires a JS/backend change, not a new native module.
    """
    driver = db.query(Driver).filter(Driver.id == driver_id).first()
    if not driver:
        raise HTTPException(status_code=404, detail="Driver not found")

    vehicle = db.query(Vehicle).filter(Vehicle.driver_id == driver_id).first()
    if vehicle:
        vehicle.plate_number = payload.plate_number
        vehicle.make_model = payload.make_model
        vehicle.roadworthy_expiry = payload.roadworthy_expiry
        vehicle.insurance_expiry = payload.insurance_expiry
        if payload.photo_url is not None:
            vehicle.photo_url = payload.photo_url
    else:
        vehicle = Vehicle(driver_id=driver_id, **payload.dict())
        db.add(vehicle)

    db.commit()
    db.refresh(vehicle)
    return vehicle


@router.get("/{driver_id}/vehicle", response_model=VehicleOut)
def get_vehicle(
    driver_id: str,
    db: Session = Depends(get_db),
    _: CurrentUser = Depends(require_self_driver),
):
    vehicle = db.query(Vehicle).filter(Vehicle.driver_id == driver_id).first()
    if not vehicle:
        raise HTTPException(status_code=404, detail="No vehicle on file for this driver")
    return vehicle


@router.get("/pending", response_model=List[DriverAdminOut])
def list_pending_drivers(
    db: Session = Depends(get_db),
    _: None = Depends(require_admin),
):
    """
    What the admin needs to see BEFORE calling /verify — without this,
    there was no way to know which driver_id to approve short of querying
    the database directly.
    """
    return db.query(Driver).filter(Driver.status == DriverStatus.pending).all()


@router.post("/{driver_id}/verify")
def verify_driver(
    driver_id: str,
    db: Session = Depends(get_db),
    _: None = Depends(require_admin),
):
    driver = db.query(Driver).filter(Driver.id == driver_id).first()
    if not driver:
        raise HTTPException(status_code=404, detail="Driver not found")
    driver.status = DriverStatus.verified
    db.commit()
    return {"message": "Driver verified"}


@router.post("/{driver_id}/reject")
def reject_driver(
    driver_id: str,
    db: Session = Depends(get_db),
    _: None = Depends(require_admin),
):
    """Counterpart to /verify — moves a pending application to suspended
    rather than leaving the admin no way to decline a bad application."""
    driver = db.query(Driver).filter(Driver.id == driver_id).first()
    if not driver:
        raise HTTPException(status_code=404, detail="Driver not found")
    driver.status = DriverStatus.suspended
    db.commit()
    return {"message": "Driver rejected"}


@router.post("/{driver_id}/location")
def update_location(
    driver_id: str,
    payload: LocationUpdate,
    db: Session = Depends(get_db),
    _: CurrentUser = Depends(require_self_driver),
):
    driver = db.query(Driver).filter(Driver.id == driver_id).first()
    if not driver:
        raise HTTPException(status_code=404, detail="Driver not found")
    if driver.status != DriverStatus.verified:
        raise HTTPException(status_code=403, detail="Driver not verified")

    point = from_shape(Point(payload.lng, payload.lat), srid=4326)

    loc = db.query(DriverLocation).filter(DriverLocation.driver_id == driver_id).first()
    if loc:
        loc.location = point
        loc.heading = payload.heading
    else:
        loc = DriverLocation(driver_id=driver_id, location=point, heading=payload.heading)
        db.add(loc)

    db.commit()
    return {"message": "Location updated"}


@router.post("/{driver_id}/availability")
def set_availability(
    driver_id: str,
    available: bool,
    db: Session = Depends(get_db),
    _: CurrentUser = Depends(require_self_driver),
):
    driver = db.query(Driver).filter(Driver.id == driver_id).first()
    if not driver:
        raise HTTPException(status_code=404, detail="Driver not found")
    driver.is_available = available
    db.commit()
    return {"message": f"Driver availability set to {available}"}
