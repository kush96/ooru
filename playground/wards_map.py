import os
from pathlib import Path

import geopandas as gpd
from dotenv import load_dotenv
from sqlalchemy import create_engine, select

from app.modules.commons.models.municipal_corporations import MunicipalCorporation
from app.modules.commons.models.wards import Ward


PROJECT_DIR = Path(__file__).resolve().parent.parent
MAP_PATH = Path(__file__).resolve().parent / "wards_map.html"

if __name__ == "__main__":
    load_dotenv(PROJECT_DIR / ".env")
    engine = create_engine(os.environ["DATABASE_URL"])

    ward_query = (
        select(
            Ward.source_id,
            Ward.name,
            MunicipalCorporation.name.label("corporation"),
            Ward.boundary,
        )
        .select_from(Ward)
        .outerjoin(
            MunicipalCorporation,
            Ward.authorised_municipal_corporation_id == MunicipalCorporation.id,
        )
    )

    wards = gpd.read_postgis(ward_query, engine, geom_col="boundary")

    wards.explore(
        column="corporation",
        tooltip=["name", "source_id", "corporation"],
        tiles="OpenStreetMap",
    ).save(MAP_PATH)

    engine.dispose()
    print(f"Saved {len(wards)} wards to {MAP_PATH}")