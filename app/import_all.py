"""CLI entry point: uv run python -m app.import_all."""

import logging
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.clients.osm import OsmClient
from app.config import get_settings
from app.modules.commons.boundary_service import BoundaryService
# Register all ORM tables before create_all, independently of service construction.
from app.modules.commons.models import municipal_corporations, wards
from app.modules.commons.models.base import BaseModel
from app.modules.commons.repositories.municipal_corporations_repo import MunicipalCorporationsRepo
from app.modules.commons.repositories.wards_repo import WardsRepo
from app.modules.roads.models import roads
from app.modules.roads.repositories.roads_repo import RoadsRepo
from app.modules.roads.road_service import RoadService

logger = logging.getLogger(__name__)


def main():
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    datasets_dir = Path(__file__).resolve().parent.parent / "resources/datasets"
    logger.warning(
        "This import inserts missing records and updates matching corporations, wards and roads."
    )

    database_url = get_settings().database_url.get_secret_value()
    if not database_url:
        raise ValueError("Set DATABASE_URL in the backend .env before importing data.")
    engine = create_engine(database_url)
    try:
        BaseModel.metadata.create_all(engine)
        with Session(engine) as session, session.begin():
            corporations_repo = MunicipalCorporationsRepo(session=session)
            wards_repo = WardsRepo(session=session)
            boundaries = BoundaryService(
                corporations_repo=corporations_repo,
                wards_repo=wards_repo,
            )
            counts = boundaries.import_data(
                datasets_dir / "wards/original/gba-369-wards-december-2025.kml",
            )
        logger.info("Committed boundaries: %s", counts)

        with Session(engine) as session:
            roads_repo = RoadsRepo(session=session)
            wards_repo = WardsRepo(session=session)
            osm_client = OsmClient()
            road_service = RoadService(
                session=session,
                roads_repo=roads_repo,
                wards_repo=wards_repo,
                osm_client=osm_client,
            )
            road_service.import_data(datasets_dir / "roads")
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
