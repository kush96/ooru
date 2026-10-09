import json
import logging
from datetime import datetime
from pathlib import Path
from uuid import uuid4

import pandas as pd
from geoalchemy2 import WKTElement
from sqlalchemy import func
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.modules.roads.models.roads import Road

logger = logging.getLogger(__name__)


def import_csv_to_db(session: Session, csv_path: str | Path) -> int:
    total = 0
    for batch in pd.read_csv(csv_path, chunksize=1000, keep_default_na=False):
        records = []
        for _, road_row in batch.iterrows():
            records.append({
                "id": uuid4(),
                "osm_id": int(road_row["osm_id"]),
                "name": road_row["name"] or None,
                "road_class": road_row["road_class"],
                "geometry": WKTElement(road_row["geometry"], srid=4326),
                "tags": json.loads(road_row["source_tags"]),
                "fetched_at": datetime.fromisoformat(road_row["fetched_at"]),
            })

        insert_statement = insert(Road).values(records)

        upsert_statement = insert_statement.on_conflict_do_update(
            index_elements=[Road.osm_id],
            set_={
                "name": insert_statement.excluded.name,
                "road_class": insert_statement.excluded.road_class,
                "geometry": insert_statement.excluded.geometry,
                "tags": insert_statement.excluded.tags,
                "fetched_at": insert_statement.excluded.fetched_at,
                "update_at": func.now(),
            },
        )
        with session.begin():
            session.execute(upsert_statement)
        total += len(records)
        logger.info("Committed %s roads", total)
    return total
