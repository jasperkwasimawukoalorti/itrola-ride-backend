"""
Driver onboarding + live location updates.

MVP approach: driver signs up -> status defaults to 'pending' -> admin
manually flips to 'verified' after checking Ghana Card / license / vehicle
docs. Automated document verification can come later.

Auth model:
- /onboard is public (that's how a driver gets into the system in the first place)
- /vehicle, /location, /availability require the driver's own JWT (require_self_driver)
- /verify requires the admin key (require_admin)
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from geoalchemy2.shape import from_shape
from shapely.geometry import Point

from app.core.database import get_db
from app.core.deps import require_self_driver, require_admin, CurrentUser
from app.models.models import Driver, Vehicle, DriverLocation, DriverStatus
from app.schemas.schemas import DriverCreate, VehicleCreate, DriverOut, LocationUpdate

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
        status=DriverStatus.pending,  # admin must verify before driver can go online
    )
    db.add(driver)
    db.commit()
    db.refresh(driver)
    return driver


@router.post("/{driver_id}/vehicle")
def add_vehicle(
    driver_id: str,
    payload: VehicleCreate,
    db: Session = Depends(get_db),
    _: CurrentUser = Depends(require_self_driver),
):
    driver = db.query(Driver).filter(Driver.id == driver_id).first()
    if not driver:
        raise HTTPException(status_code=404, detail="Driver not found")

    vehicle = Vehicle(driver_id=driver_id, **payload.dict())
    db.add(vehicle)
    db.commit()
    return {"message": "Vehicle added, pending verification"}


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
