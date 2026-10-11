"""Use the cached road CSV (fetch it if missing), then import it in batches."""

import json
import logging
from datetime import datetime
from pathlib import Path

import pandas as pd
from shapely import union_all
from sqlalchemy.orm import Session

from app.clients.osm import OsmClient
from app.modules.commons.repositories.wards_repo import WardsRepo
from app.modules.roads.repositories.roads_repo import RoadsRepo

logger = logging.getLogger(__name__)


class RoadService:
    """Coordinate imports; both injected repositories must use the same session."""

    def __init__(
        self,
        session: Session,
        roads_repo: RoadsRepo,
        wards_repo: WardsRepo,
        osm_client: OsmClient,
    ):
        self.session = session
        self.roads_repo = roads_repo
        self.wards_repo = wards_repo
        self.osm_client = osm_client

    def import_data(self, roads_dir: Path) -> int:
        csv_path = roads_dir / "bengaluru_roads.csv"
        if not csv_path.is_file():
            with self.session.begin():
                boundaries = self.wards_repo.get_boundaries()
            if not boundaries:
                raise ValueError("Import ward boundaries before fetching roads.")
            self.osm_client.fetch_roads_to_csv(union_all(boundaries), csv_path)

        total = 0
        for batch in pd.read_csv(csv_path, chunksize=1000, keep_default_na=False):
            records = []
            for _, row in batch.iterrows():
                records.append({
                    "osm_id": int(row["osm_id"]),
                    "name": row["name"] or None,
                    "road_class": row["road_class"],
                    "geometry": row["geometry"],
                    "tags": json.loads(row["source_tags"]),
                    "fetched_at": datetime.fromisoformat(row["fetched_at"]),
                })
            with self.session.begin():
                self.roads_repo.upsert_many(records)
            total += len(records)
            logger.info("Committed %s roads", total)
        return total
