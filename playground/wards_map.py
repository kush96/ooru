from pathlib import Path

import geopandas as gpd
from sqlalchemy import create_engine, select

from app.config import get_settings
from app.modules.commons.models.municipal_corporations import MunicipalCorporation
from app.modules.commons.models.wards import Ward


MAP_PATH = Path(__file__).resolve().parent / "wards_map.html"

if __name__ == "__main__":
    database_url = get_settings().database_url.get_secret_value()
    if not database_url:
        raise ValueError("Set DATABASE_URL in the backend .env before building the map.")
    engine = create_engine(database_url)

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
