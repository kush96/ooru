"""Upsert road records by OSM ID. The caller owns the transaction."""

from uuid import uuid4

from geoalchemy2 import WKTElement
from sqlalchemy import func
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.modules.roads.models.roads import Road


class RoadsRepo:
    def __init__(self, session: Session):
        self.session = session

    def upsert_many(self, records: list[dict]) -> None:
        if not records:
            return
        values = [
            {**record, "id": uuid4(), "geometry": WKTElement(record["geometry"], srid=4326)}
            for record in records
        ]
        statement = insert(Road).values(values)
        self.session.execute(statement.on_conflict_do_update(
            index_elements=[Road.osm_id],
            set_={
                "name": statement.excluded.name,
                "road_class": statement.excluded.road_class,
                "geometry": statement.excluded.geometry,
                "tags": statement.excluded.tags,
                "fetched_at": statement.excluded.fetched_at,
                "update_at": func.now(),
            },
        ))
