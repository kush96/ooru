"""Prepare corporation/ward source data and save it through their repositories."""

import logging
from pathlib import Path

import geopandas as gpd
from shapely import make_valid
from shapely.geometry import MultiPolygon, Polygon

from app.modules.commons.repositories.municipal_corporations_repo import MunicipalCorporationsRepo
from app.modules.commons.repositories.wards_repo import WardsRepo

logger = logging.getLogger(__name__)

CORPORATIONS = [
    ("1", "Bengaluru Central City Corporation", "https://bengalurucentral.karnataka.gov.in/"),
    ("2", "Bengaluru North City Corporation", "https://bengalurunorth.karnataka.gov.in/"),
    ("3", "Bengaluru East City Corporation", "https://bengalurueast.karnataka.gov.in/"),
    ("4", "Bengaluru South City Corporation", "https://bengalurusouth.karnataka.gov.in/"),
    ("5", "Bengaluru West City Corporation", "https://bengaluruwest.karnataka.gov.in/"),
]


class BoundaryService:
    def __init__(self, corporations_repo: MunicipalCorporationsRepo, wards_repo: WardsRepo):
        self.corporations_repo = corporations_repo
        self.wards_repo = wards_repo

    @staticmethod
    def _repair_boundary(boundary) -> MultiPolygon:
        repaired = make_valid(boundary)
        polygons = []
        for geometry in getattr(repaired, "geoms", [repaired]):
            if isinstance(geometry, Polygon):
                polygons.append(geometry)
            elif isinstance(geometry, MultiPolygon):
                polygons.extend(geometry.geoms)
        return MultiPolygon(polygons)

    def import_data(self, kml_path: str | Path) -> dict[str, int]:
        """Import both datasets together; the caller controls commit/rollback."""
        created = self.corporations_repo.upsert_many([
            {"source_id": source_id, "name": name, "official_website": website}
            for source_id, name, website in CORPORATIONS
        ])
        corporation_ids = self.corporations_repo.get_ids_by_source_id()
        records = []
        skipped = 0
        for _, row in gpd.read_file(kml_path).iterrows():
            corporation_id = corporation_ids.get(str(row["corporation_id"]))
            if corporation_id is None:
                logger.warning("%s: corporation %s not found; storing NULL FK", row["ward_name"], row["corporation_id"])
            boundary = self._repair_boundary(row["geometry"])
            if boundary.is_empty or not boundary.is_valid:
                logger.warning("Skipping unusable boundary: %s", row["ward_name"])
                skipped += 1
                continue
            records.append({
                "authorised_municipal_corporation_id": corporation_id,
                "source_id": int(row["ward_id"]),
                "name": row["ward_name"],
                "total_population": int(float(row["TOT_P"])),
                "total_male_population": int(float(row["TOT_M"])),
                "total_female_population": int(float(row["TOT_F"])),
                "boundary": boundary,
            })
        counts = self.wards_repo.upsert_many(records)
        return {"corporations_created": created, **counts, "skipped": skipped}
