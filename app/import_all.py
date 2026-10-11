"""CLI entry point: uv run python -m app.import_all."""

import logging
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.config import get_settings
from app.dependencies import get_boundary_service, get_road_service
# Register all ORM tables before create_all, independently of service construction.
from app.modules.commons.models import municipal_corporations, wards
from app.modules.commons.models.base import BaseModel
from app.modules.roads.models import roads

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
            boundaries = get_boundary_service(session)
            counts = boundaries.import_data(
                datasets_dir / "wards/original/gba-369-wards-december-2025.kml",
            )
        logger.info("Committed boundaries: %s", counts)

        with Session(engine) as session:
            road_service = get_road_service(session)
            road_service.import_data(datasets_dir / "roads")
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
