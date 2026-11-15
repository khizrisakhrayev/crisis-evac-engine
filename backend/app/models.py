"""ORM models. Enum-like fields are plain strings; allowed values noted in comments."""
from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Index, Integer, String, UniqueConstraint, text
from sqlalchemy.orm import Mapped, mapped_column

from . import config
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
    is_accessible: Mapped[bool] = mapped_column(Boolean, default=True)  # step-free / wheelchair-usable
    is_reserve: Mapped[bool] = mapped_column(Boolean, default=False)  # closed until a Red Alert opens it
    is_temporary: Mapped[bool] = mapped_column(Boolean, default=False)  # created on confirm when no reserve left
    # Real walking access from the road graph to the entrance (from data/road_geometry.json); None for temporary ones.
    access_node_id: Mapped[int | None] = mapped_column(ForeignKey("road_nodes.id"), nullable=True)
    access_path: Mapped[list | None] = mapped_column(JSON, nullable=True)  # [[lat, lon], ...] node -> shelter
    access_m: Mapped[float | None] = mapped_column(Float, nullable=True)
    # All candidate entries [{"node_id", "path", "m"}] (3 nearest nodes); routing picks the cheapest total walk.
    access_options: Mapped[list | None] = mapped_column(JSON, nullable=True)


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
    is_accessible: Mapped[bool] = mapped_column(Boolean, default=True)  # False = stairs / steep link
    geometry: Mapped[list | None] = mapped_column(JSON, nullable=True)  # real street polyline [[lat, lon], ...] from -> to


class SOS(Base):
    __tablename__ = "sos"
    # At most one active SOS per citizen (repeat SOS updates it; see services/sos.py).
    __table_args__ = (
        Index("uq_sos_active_citizen", "citizen_id", unique=True, sqlite_where=text("status = 'active'")),
        Index("ix_sos_status_created", "status", "created_at"),
        Index("ix_sos_zone_created", "zone_id", "created_at"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    citizen_id: Mapped[str] = mapped_column(String(64), index=True)
    lat: Mapped[float] = mapped_column(Float)
    lon: Mapped[float] = mapped_column(Float)
    hazard_type: Mapped[str] = mapped_column(String(16))  # fire | collapse | flood | medical
    status: Mapped[str] = mapped_column(String(16), default="active")  # active | safe | resolved
    zone_id: Mapped[int | None] = mapped_column(ForeignKey("zones.id"), nullable=True)
    priority: Mapped[int] = mapped_column(Integer, default=config.SOS_PRIORITY_NORMAL)  # 1 = critical, 2 = normal
    is_priority_citizen: Mapped[bool] = mapped_column(Boolean, default=False)
    # Flood protection: too many citizen ids from one IP. Excluded from Red Alerts, the feed, KPIs and the map.
    suspected_spam: Mapped[bool] = mapped_column(Boolean, default=False)
    source_ip: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class User(Base):
    """Staff account (dispatcher / admin). Password stored as a PBKDF2 hash."""
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(64), unique=True)
    role: Mapped[str] = mapped_column(String(32))
    password_hash: Mapped[str] = mapped_column(String(256))


class Brigade(Base):
    __tablename__ = "brigades"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(16), default="available")  # available | dispatched
    zone_id: Mapped[int] = mapped_column(ForeignKey("zones.id"))  # home zone; location = zone centre
    target_zone_id: Mapped[int | None] = mapped_column(ForeignKey("zones.id"), nullable=True)
    alert_id: Mapped[int | None] = mapped_column(Integer, nullable=True)  # no FK: avoids alerts<->brigades cycle


class Alert(Base):
    """Red Alert. Codes only (kind, severity, status, action_code) - the UI translates."""
    __tablename__ = "alerts"
    # At most one OPEN alert per (sos_cluster, zone) and per (shelter_overflow, shelter).
    __table_args__ = (
        Index("uq_alert_open_cluster_zone", "kind", "zone_id", unique=True,
              sqlite_where=text("status = 'open' AND kind = 'sos_cluster'")),
        Index("uq_alert_open_overflow_shelter", "kind", "shelter_id", unique=True,
              sqlite_where=text("status = 'open' AND kind = 'shelter_overflow'")),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    kind: Mapped[str] = mapped_column(String(32))  # sos_cluster | shelter_overflow
    severity: Mapped[str] = mapped_column(String(16), default=config.ALERT_SEVERITY)
    zone_id: Mapped[int | None] = mapped_column(ForeignKey("zones.id"), nullable=True)
    shelter_id: Mapped[int | None] = mapped_column(ForeignKey("shelters.id"), nullable=True)
    lat: Mapped[float] = mapped_column(Float)
    lon: Mapped[float] = mapped_column(Float)
    sos_count: Mapped[int] = mapped_column(Integer, default=0)
    sos_ids: Mapped[list] = mapped_column(JSON, default=list)
    has_priority_sos: Mapped[bool] = mapped_column(Boolean, default=False)
    status: Mapped[str] = mapped_column(String(16), default="open")  # open | confirmed
    action_code: Mapped[str] = mapped_column(String(64), default=config.ALERT_ACTION_CODE)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    brigade_id: Mapped[int | None] = mapped_column(ForeignKey("brigades.id"), nullable=True)
    new_shelter_id: Mapped[int | None] = mapped_column(ForeignKey("shelters.id"), nullable=True)
    brigade_shortage: Mapped[bool] = mapped_column(Boolean, default=False)


class RouteCache(Base):
    """Last good route per (snapped origin node, shelter, accessible) - local backup when routing is degraded."""
    __tablename__ = "route_cache"
    __table_args__ = (UniqueConstraint("origin_node_id", "shelter_id", "accessible", name="uq_route_cache_key"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    origin_node_id: Mapped[int] = mapped_column(ForeignKey("road_nodes.id"))
    shelter_id: Mapped[int] = mapped_column(ForeignKey("shelters.id"))
    accessible: Mapped[bool] = mapped_column(Boolean, default=False)
    path_json: Mapped[list] = mapped_column(JSON)
    distance_m: Mapped[int] = mapped_column(Integer)
    edge_ids_json: Mapped[list] = mapped_column(JSON)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class DistanceMatrix(Base):
    """Static zone-centre -> shelter road distances (closures ignored), precomputed at startup."""
    __tablename__ = "distance_matrix"
    __table_args__ = (UniqueConstraint("zone_id", "shelter_id", name="uq_distance_matrix_key"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    zone_id: Mapped[int] = mapped_column(ForeignKey("zones.id"))
    shelter_id: Mapped[int] = mapped_column(ForeignKey("shelters.id"))
    distance_m: Mapped[int] = mapped_column(Integer)
