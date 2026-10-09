import logging
import os
from pathlib import Path

import osmnx as ox
from dotenv import load_dotenv
from geoalchemy2.shape import to_shape
from shapely import union_all
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.modules.commons.imports.import_municipal_corporations import import_municipal_corporations
from app.modules.commons.imports.import_wards import import_wards
from app.modules.commons.models.base import BaseModel
from app.modules.commons.models.wards import Ward
from app.modules.roads.imports.import_csv_to_db import import_csv_to_db
from app.modules.roads.imports.import_osm_to_csv import import_osm_to_csv

logger = logging.getLogger(__name__)


def main():
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    project_dir = Path(__file__).resolve().parent.parent
    load_dotenv(project_dir / ".env")
    logger.warning(
        "This import inserts missing records and updates matching corporations, wards and roads."
    )

    engine = create_engine(os.environ["DATABASE_URL"])
    try:
        BaseModel.metadata.create_all(engine)
        with Session(engine) as session, session.begin():
            corporations = import_municipal_corporations(session)
            wards = import_wards(
                session,
                project_dir / "resources/datasets/wards/original/gba-369-wards-december-2025.kml",
            )
        logger.info("Committed: %s new corporations; wards: %s", corporations, wards)

        csv_path = project_dir / "resources/datasets/roads/bengaluru_roads.csv"
        if csv_path.is_file():
            logger.info("Using existing roads CSV: %s", csv_path)
        else:
            ox.settings.cache_folder = project_dir / "resources/datasets/roads/osmnx_cache"
            ox.settings.use_cache = True
            with Session(engine) as session:
                boundaries = session.scalars(select(Ward.boundary)).all()
            boundary = union_all([to_shape(shape) for shape in boundaries])
            import_osm_to_csv(boundary, csv_path)

        with Session(engine) as session:
            import_csv_to_db(session, csv_path)
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
