"""Repository behavior with real ORM models and fake sessions; no database writes."""

from datetime import UTC, datetime
from unittest.mock import MagicMock
from uuid import uuid4

from geoalchemy2.shape import from_shape, to_shape
from shapely.geometry import MultiPolygon, Polygon
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import Session

from app.modules.commons.models.municipal_corporations import MunicipalCorporation
from app.modules.commons.models.wards import Ward
from app.modules.commons.repositories.municipal_corporations_repo import MunicipalCorporationsRepo
from app.modules.commons.repositories.wards_repo import WardsRepo
from app.modules.roads.repositories.roads_repo import RoadsRepo


BOUNDARY = MultiPolygon([Polygon([(0, 0), (1, 0), (1, 1), (0, 0)])])


def ward_record(corporation_id, name="Ward A"):
    return {
        "source_id": 1, "name": name,
        "authorised_municipal_corporation_id": corporation_id,
        "total_population": 100, "total_male_population": 40,
        "total_female_population": 60, "boundary": BOUNDARY,
    }


def test_corporations_update_existing_and_do_not_duplicate():
    existing = MunicipalCorporation(id=uuid4(), source_id="1", name="Central", official_website="old")
    session = MagicMock(spec=Session)
    session.scalars.return_value = [existing]
    records = [
        {"source_id": "1", "name": "Central", "official_website": "updated"},
        {"source_id": "2", "name": "North", "official_website": "north"},
    ]
    assert MunicipalCorporationsRepo(session).upsert_many(records + [records[1]]) == 1
    assert existing.official_website == "updated"
    session.add.assert_called_once()
    session.flush.assert_called_once()
    session.commit.assert_not_called()


def test_corporation_source_id_lookup():
    corporation_id = uuid4()
    session = MagicMock(spec=Session)
    session.execute.return_value.all.return_value = [("1", corporation_id)]
    assert MunicipalCorporationsRepo(session).get_ids_by_source_id() == {"1": corporation_id}


def test_wards_resolve_missing_fk_and_distinguish_corporations():
    central, north = uuid4(), uuid4()
    existing = Ward(id=uuid4(), source_id=1, name="Ward A", authorised_municipal_corporation_id=None)
    original_id = existing.id
    session = MagicMock(spec=Session)
    session.scalars.return_value = [existing]
    records = [ward_record(central), ward_record(north), ward_record(central)]
    repo = WardsRepo(session)
    assert repo.upsert_many(records) == {"created": 1, "updated": 2}
    assert existing.id == original_id
    assert existing.authorised_municipal_corporation_id == central
    assert existing.total_population == 100
    assert to_shape(existing.boundary).equals(BOUNDARY)
    created = session.add.call_args.args[0]
    assert created.authorised_municipal_corporation_id == north
    session.add.assert_called_once()
    session.commit.assert_not_called()

    session.reset_mock()
    session.scalars.return_value = [existing, created]
    assert repo.upsert_many(records) == {"created": 0, "updated": 3}
    session.add.assert_not_called()


def test_unresolved_ward_ids_keep_different_names_separate():
    session = MagicMock(spec=Session)
    session.scalars.return_value = []
    records = [ward_record(None, "A"), ward_record(None, "B"), ward_record(None, "A")]
    assert WardsRepo(session).upsert_many(records) == {"created": 2, "updated": 1}


def test_boundary_query_returns_shapes():
    session = MagicMock(spec=Session)
    session.scalars.return_value = [from_shape(BOUNDARY, srid=4326)]
    assert WardsRepo(session).get_boundaries()[0].equals(BOUNDARY)


def test_road_upsert_uses_osm_id_and_leaves_transaction_to_caller():
    session = MagicMock(spec=Session)
    RoadsRepo(session).upsert_many([{
        "osm_id": 42, "name": None, "road_class": "residential",
        "geometry": "LINESTRING (0 0, 1 1)", "tags": {"highway": "residential"},
        "fetched_at": datetime.now(UTC),
    }])
    statement = session.execute.call_args.args[0].compile(dialect=postgresql.dialect())
    assert "ON CONFLICT (osm_id) DO UPDATE" in str(statement)
    assert "geometry = excluded.geometry" in str(statement)
    assert statement.params["osm_id_m0"] == 42
    assert statement.params["geometry_m0"].srid == 4326
    session.begin.assert_not_called()
    session.commit.assert_not_called()


def test_empty_road_batch_does_not_execute_sql():
    session = MagicMock(spec=Session)
    RoadsRepo(session).upsert_many([])
    session.execute.assert_not_called()
