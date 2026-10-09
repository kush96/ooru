import json
import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import geopandas as gpd
import osmnx as ox
import pandas as pd
from shapely import MultiPolygon, Polygon

logger: logging.Logger = logging.getLogger(__name__)


def import_osm_to_csv(boundary: Polygon | MultiPolygon, csv_path: str | Path) -> int:
    features: gpd.GeoDataFrame = ox.features_from_polygon(
        boundary,
        tags={"highway": ["primary", "secondary", "tertiary", "residential", "service"]},
    )
    roads: gpd.GeoDataFrame = features.loc[
        (features.index.get_level_values("element") == "way")
        & (features.geometry.geom_type == "LineString")
    ]

    fetched_at: str = datetime.now(UTC).isoformat()
    records: list[dict[str, Any]] = []

    for (_, osm_id), road_row in roads.iterrows():
        source_tags: dict[str, Any] = road_row.drop(labels="geometry").dropna().to_dict()
        records.append({
            "osm_id": osm_id,
            "name": source_tags.get("name"),
            "road_class": source_tags["highway"],
            "geometry": road_row["geometry"].wkt,
            "source_tags": json.dumps(source_tags, ensure_ascii=False),
            "fetched_at": fetched_at,
        })
    road_csv: pd.DataFrame = pd.DataFrame(records)

    csv_path = Path(csv_path)
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    road_csv.to_csv(csv_path, index=False)
    logger.info("Saved %s OSM road ways to %s", len(road_csv), csv_path)
    return len(road_csv)
