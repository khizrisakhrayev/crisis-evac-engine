from sqlalchemy.orm import Session

from ..models import RoadEdge, RoadNode
from .routing_provider import invalidate_graph


def _out(e: RoadEdge, nodes: dict[int, RoadNode]) -> dict:
    a, b = nodes[e.from_node], nodes[e.to_node]
    return dict(id=e.id, from_node=e.from_node, to_node=e.to_node, from_lat=a.lat, from_lon=a.lon,
                to_lat=b.lat, to_lon=b.lon, length_m=e.length_m, is_closed=e.is_closed, is_accessible=e.is_accessible)


def list_roads(db: Session) -> list[dict]:
    nodes = {n.id: n for n in db.query(RoadNode).all()}
    return [_out(e, nodes) for e in db.query(RoadEdge).order_by(RoadEdge.id).all()]


def set_closed(db: Session, edge_id: int, closed: bool) -> dict | None:
    edge = db.get(RoadEdge, edge_id)
    if edge is None:
        return None
    edge.is_closed = closed
    db.commit()
    invalidate_graph(db)
    return _out(edge, {nid: db.get(RoadNode, nid) for nid in (edge.from_node, edge.to_node)})
