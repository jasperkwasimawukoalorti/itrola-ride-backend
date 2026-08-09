"""
SQLAlchemy models matching the data model design.
Uses GeoAlchemy2 for PostGIS geography columns.
"""
import uuid
import enum
from sqlalchemy import (
    Column, String, Float, DateTime, ForeignKey, Enum, Boolean, Integer, Text
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from geoalchemy2 import Geography

from app.core.database import Base


def gen_uuid():
    return str(uuid.uuid4())


class DriverStatus(str, enum.Enum):
    pending = "pending"
    verified = "verified"
    suspended = "suspended"


class TripStatus(str, enum.Enum):
    requested = "requested"
    matched = "matched"
    en_route = "en_route"
    in_progress = "in_progress"
    completed = "completed"
    cancelled = "cancelled"


class PaymentMethod(str, enum.Enum):
    cash = "cash"
    momo = "momo"


class PaymentStatus(str, enum.Enum):
    pending = "pending"
    paid = "paid"
    failed = "failed"


class RatedBy(str, enum.Enum):
    rider = "rider"
    driver = "driver"


class User(Base):
    """Riders."""
    __tablename__ = "users"

    id = Column(UUID(as_uuid=False), primary_key=True, default=gen_uuid)
    phone = Column(String, unique=True, nullable=False, index=True)
    name = Column(String, nullable=True)
    momo_number = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    trips = relationship("Trip", back_populates="rider")


class Driver(Base):
    __tablename__ = "drivers"

    id = Column(UUID(as_uuid=False), primary_key=True, default=gen_uuid)
    phone = Column(String, unique=True, nullable=False, index=True)
    name = Column(String, nullable=True)
    ghana_card_number = Column(String, nullable=True)
    license_number = Column(String, nullable=True)
    license_expiry = Column(DateTime, nullable=True)
    status = Column(Enum(DriverStatus), default=DriverStatus.pending, nullable=False)
    is_available = Column(Boolean, default=False)
    rating_avg = Column(Float, default=5.0)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    vehicle = relationship("Vehicle", back_populates="driver", uselist=False)
    trips = relationship("Trip", back_populates="driver")
    location = relationship("DriverLocation", back_populates="driver", uselist=False)


class Vehicle(Base):
    __tablename__ = "vehicles"

    id = Column(UUID(as_uuid=False), primary_key=True, default=gen_uuid)
    driver_id = Column(UUID(as_uuid=False), ForeignKey("drivers.id"), nullable=False)
    plate_number = Column(String, nullable=False)
    make_model = Column(String, nullable=True)
    roadworthy_expiry = Column(DateTime, nullable=True)
    insurance_expiry = Column(DateTime, nullable=True)
    photo_url = Column(String, nullable=True)

    driver = relationship("Driver", back_populates="vehicle")


class DriverLocation(Base):
    """
    High-frequency updated table. In production, consider moving this
    to Redis or Firebase Realtime DB instead of Postgres to avoid write load.
    Kept here for MVP simplicity.
    """
    __tablename__ = "driver_locations"

    driver_id = Column(UUID(as_uuid=False), ForeignKey("drivers.id"), primary_key=True)
    location = Column(Geography(geometry_type="POINT", srid=4326), nullable=False)
    heading = Column(Float, nullable=True)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    driver = relationship("Driver", back_populates="location")


class Trip(Base):
    __tablename__ = "trips"

    id = Column(UUID(as_uuid=False), primary_key=True, default=gen_uuid)
    rider_id = Column(UUID(as_uuid=False), ForeignKey("users.id"), nullable=False)
    driver_id = Column(UUID(as_uuid=False), ForeignKey("drivers.id"), nullable=True)
    status = Column(Enum(TripStatus), default=TripStatus.requested, nullable=False)

    pickup_location = Column(Geography(geometry_type="POINT", srid=4326), nullable=False)
    dropoff_location = Column(Geography(geometry_type="POINT", srid=4326), nullable=False)

    requested_at = Column(DateTime(timezone=True), server_default=func.now())
    matched_at = Column(DateTime(timezone=True), nullable=True)
    started_at = Column(DateTime(timezone=True), nullable=True)
    completed_at = Column(DateTime(timezone=True), nullable=True)

    fare_estimate = Column(Float, nullable=True)
    fare_final = Column(Float, nullable=True)
    payment_method = Column(Enum(PaymentMethod), default=PaymentMethod.cash)
    payment_status = Column(Enum(PaymentStatus), default=PaymentStatus.pending)

    rider = relationship("User", back_populates="trips")
    driver = relationship("Driver", back_populates="trips")


class Rating(Base):
    __tablename__ = "ratings"

    id = Column(UUID(as_uuid=False), primary_key=True, default=gen_uuid)
    trip_id = Column(UUID(as_uuid=False), ForeignKey("trips.id"), nullable=False)
    rated_by = Column(Enum(RatedBy), nullable=False)
    score = Column(Integer, nullable=False)
    comment = Column(Text, nullable=True)
