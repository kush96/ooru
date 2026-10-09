import logging
from pathlib import Path
from uuid import uuid4

import geopandas as gpd
from geoalchemy2.shape import from_shape
from shapely import make_valid
from shapely.geometry import MultiPolygon, Polygon
from shapely.validation import explain_validity
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.commons.models.municipal_corporations import MunicipalCorporation
from app.modules.commons.models.wards import Ward

logger = logging.getLogger(__name__)


def repair_boundary(boundary) -> MultiPolygon:
    repaired = make_valid(boundary)
    polygons = []
    for geometry in getattr(repaired, "geoms", [repaired]):
        if isinstance(geometry, Polygon):
            polygons.append(geometry)
        elif isinstance(geometry, MultiPolygon):
            polygons.extend(geometry.geoms)
    return MultiPolygon(polygons)


def import_wards(session: Session, kml_path: str | Path) -> dict[str, int]:
    """Import valid boundaries; leave commit/rollback to the caller."""
    corporations = {
        corporation.source_id: corporation.id
        for corporation in session.scalars(select(MunicipalCorporation))
    }
    existing = {
        (ward.authorised_municipal_corporation_id, ward.source_id,
         ward.name if ward.authorised_municipal_corporation_id is None else None): ward
        for ward in session.scalars(select(Ward))
    }
    counts = {"created": 0, "updated": 0, "skipped": 0}

    wards_source_data = gpd.read_file(kml_path)
    for _, ward_row in wards_source_data.iterrows():
        corporation_source_id = str(ward_row["corporation_id"])
        corporation_id = corporations.get(corporation_source_id)
        if corporation_id is None:
            logger.warning("%s: corporation source ID %s not found; storing NULL FK", ward_row["ward_name"], corporation_source_id)
        ward_source_id = int(ward_row["ward_id"])
        boundary = ward_row["geometry"]

        # Repair self-intersections present in the source boundary.
        if not boundary.is_valid:
            logger.warning("Repairing %s: %s", ward_row["ward_name"], explain_validity(boundary))
            boundary = repair_boundary(boundary)
        # Ward numbers repeat across corporations; retain name for unresolved FKs.
        key = (corporation_id, ward_source_id, ward_row["ward_name"] if corporation_id is None else None)
        ward = existing.get(key) or existing.get((None, ward_source_id, ward_row["ward_name"]))
        if ward is None:
            ward = Ward(
                id=uuid4(),
                authorised_municipal_corporation_id=corporation_id,
                source_id=ward_source_id,
            )
            session.add(ward)
            existing[key] = ward
            counts["created"] += 1
        else:
            counts["updated"] += 1

        ward.authorised_municipal_corporation_id = corporation_id
        ward.name = ward_row["ward_name"]
        ward.total_population = int(float(ward_row["TOT_P"]))
        ward.total_male_population = int(float(ward_row["TOT_M"]))
        ward.total_female_population = int(float(ward_row["TOT_F"]))
        ward.boundary = from_shape(boundary, srid=4326)

    return counts
