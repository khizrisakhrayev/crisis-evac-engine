"""ORM models. Enum-like fields are plain strings; allowed values noted in comments."""
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Index, Integer, String, text
from sqlalchemy.orm import Mapped, mapped_column

from .db import Base
from .services.clock import utcnow  # naive UTC


class Zone(Base):
    __tablename__ = "zones"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(64), unique=True)
    center_lat: Mapped[float] = mapped_column(Float)
    center_lon: Mapped[float] = mapped_column(Float)


class Shelter(Base):
    __tablename__ = "shelters"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(128))
    type: Mapped[str] = mapped_column(String(16))  # shelter | park | stadium
    lat: Mapped[float] = mapped_column(Float)
    lon: Mapped[float] = mapped_column(Float)
    capacity: Mapped[int] = mapped_column(Integer)
    current: Mapped[int] = mapped_column(Integer, default=0)
    zone_id: Mapped[int] = mapped_column(ForeignKey("zones.id"))
    is_open: Mapped[bool] = mapped_column(Boolean, default=True)


class RoadNode(Base):
    __tablename__ = "road_nodes"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(128))
    lat: Mapped[float] = mapped_column(Float)
    lon: Mapped[float] = mapped_column(Float)
    zone_id: Mapped[int] = mapped_column(ForeignKey("zones.id"))


class RoadEdge(Base):
    __tablename__ = "road_edges"
    id: Mapped[int] = mapped_column(primary_key=True)
    from_node: Mapped[int] = mapped_column(ForeignKey("road_nodes.id"))
    to_node: Mapped[int] = mapped_column(ForeignKey("road_nodes.id"))
    length_m: Mapped[float] = mapped_column(Float)
    is_closed: Mapped[bool] = mapped_column(Boolean, default=False)


class SOS(Base):
    __tablename__ = "sos"
    # At most one active SOS per citizen (repeat SOS updates it; see services/sos.py).
    __table_args__ = (
        Index("uq_sos_active_citizen", "citizen_id", unique=True, sqlite_where=text("status = 'active'")),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    citizen_id: Mapped[str] = mapped_column(String(64), index=True)
    lat: Mapped[float] = mapped_column(Float)
    lon: Mapped[float] = mapped_column(Float)
    hazard_type: Mapped[str] = mapped_column(String(16))  # fire | collapse | flood | medical
    status: Mapped[str] = mapped_column(String(16), default="active")  # active | safe | resolved
    zone_id: Mapped[int | None] = mapped_column(ForeignKey("zones.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Brigade(Base):
    __tablename__ = "brigades"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(16), default="available")  # available | dispatched
    zone_id: Mapped[int] = mapped_column(ForeignKey("zones.id"))


class Alert(Base):
    __tablename__ = "alerts"
    id: Mapped[int] = mapped_column(primary_key=True)
    kind: Mapped[str] = mapped_column(String(32))
    reason: Mapped[str] = mapped_column(String(256))
    zone_id: Mapped[int | None] = mapped_column(ForeignKey("zones.id"), nullable=True)
    shelter_id: Mapped[int | None] = mapped_column(ForeignKey("shelters.id"), nullable=True)
    status: Mapped[str] = mapped_column(String(16), default="open")  # open | confirmed
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
