"""Import orchestration with fake repositories and network; real source parsing."""

from unittest.mock import MagicMock, Mock
from uuid import uuid4

import geopandas as gpd
import pandas as pd
import pytest
from pydantic import SecretStr
from shapely.geometry import LineString, MultiPolygon, Polygon
from sqlalchemy.orm import Session

from app.clients import osm
from app import import_all
from app.modules.commons import boundary_service as boundaries
from app.modules.commons.repositories.municipal_corporations_repo import MunicipalCorporationsRepo
from app.modules.commons.repositories.wards_repo import WardsRepo
from app.modules.roads.repositories.roads_repo import RoadsRepo
from app.modules.roads.road_service import RoadService


POLYGON = Polygon([(0, 0), (1, 0), (1, 1), (0, 0)])
ROAD = {
    "osm_id": 42, "name": "", "road_class": "residential",
    "geometry": "LINESTRING (0 0, 1 1)",
    "source_tags": '{"highway": "residential"}',
    "fetched_at": "2026-10-10T00:00:00+00:00",
}


@pytest.fixture
def road_service():
    return RoadService(
        session=MagicMock(spec=Session), roads_repo=Mock(spec=RoadsRepo),
        wards_repo=Mock(spec=WardsRepo), osm_client=Mock(spec=osm.OsmClient),
    )


def test_boundary_service_parses_then_calls_repositories(monkeypatch):
    corporation_id = uuid4()
    row = {"corporation_id": "1", "ward_id": "1", "ward_name": "A",
           "TOT_P": "100.0", "TOT_M": "40.0", "TOT_F": "60.0", "geometry": POLYGON}
    bowtie = Polygon([(0, 0), (1, 1), (1, 0), (0, 1), (0, 0)])
    data = gpd.GeoDataFrame([
        row,
        {**row, "ward_name": "B", "ward_id": "2", "corporation_id": "unknown", "geometry": bowtie},
        {**row, "ward_name": "C", "geometry": LineString([(0, 0), (1, 1)])},
    ])
    monkeypatch.setattr(boundaries.gpd, "read_file", Mock(return_value=data))
    corporations_repo = Mock(spec=MunicipalCorporationsRepo)
    corporations_repo.upsert_many.return_value = 5
    corporations_repo.get_ids_by_source_id.return_value = {"1": corporation_id}
    wards_repo = Mock(spec=WardsRepo)
    wards_repo.upsert_many.return_value = {"created": 2, "updated": 0}
    service = boundaries.BoundaryService(corporations_repo, wards_repo)
    result = service.import_data("test.kml")
    assert result == {"corporations_created": 5, "created": 2, "updated": 0, "skipped": 1}
    records = wards_repo.upsert_many.call_args.args[0]
    assert records[0]["authorised_municipal_corporation_id"] == corporation_id
    assert records[1]["authorised_municipal_corporation_id"] is None
    assert records[0]["total_population"] == 100
    assert all(isinstance(record["boundary"], MultiPolygon) and record["boundary"].is_valid for record in records)
    corporations_repo.upsert_many.assert_called_once()
    wards_repo.upsert_many.assert_called_once()


def test_cached_roads_skip_network_and_commit_in_batches(road_service, tmp_path):
    pd.DataFrame([{**ROAD, "osm_id": i} for i in range(1001)]).to_csv(tmp_path / "bengaluru_roads.csv", index=False)
    assert road_service.import_data(tmp_path) == 1001
    save = road_service.roads_repo.upsert_many
    assert [len(call.args[0]) for call in save.call_args_list] == [1000, 1]
    first = save.call_args_list[0].args[0][0]
    assert first["name"] is None
    assert first["tags"] == {"highway": "residential"}
    assert first["fetched_at"].tzinfo is not None
    assert road_service.session.begin.call_count == 2
    road_service.osm_client.fetch_roads_to_csv.assert_not_called()


def test_missing_roads_fetch_using_repository_boundaries(road_service, tmp_path):
    road_service.wards_repo.get_boundaries.return_value = [POLYGON]
    def fetch(boundary, path):
        assert boundary.equals(POLYGON)
        pd.DataFrame([ROAD]).to_csv(path, index=False)
    road_service.osm_client.fetch_roads_to_csv.side_effect = fetch
    assert road_service.import_data(tmp_path) == 1
    assert road_service.session.begin.call_count == 2  # Boundary read, then road write.
    road_service.osm_client.fetch_roads_to_csv.assert_called_once()
    road_service.roads_repo.upsert_many.assert_called_once()


def test_missing_boundaries_stop_before_network(road_service, tmp_path):
    road_service.wards_repo.get_boundaries.return_value = []
    with pytest.raises(ValueError, match="Import ward boundaries"):
        road_service.import_data(tmp_path)
    road_service.osm_client.fetch_roads_to_csv.assert_not_called()


def test_road_write_failure_exits_transaction_as_failure(road_service, tmp_path):
    pd.DataFrame([ROAD]).to_csv(tmp_path / "bengaluru_roads.csv", index=False)
    road_service.roads_repo.upsert_many.side_effect = RuntimeError("write failed")
    with pytest.raises(RuntimeError, match="write failed"):
        road_service.import_data(tmp_path)
    assert road_service.session.begin.return_value.__exit__.call_args.args[0] is RuntimeError


def test_osm_empty_result_still_writes_readable_csv(monkeypatch, tmp_path):
    data = gpd.GeoDataFrame(
        {"highway": ["residential"], "geometry": [POLYGON]},
        index=pd.MultiIndex.from_tuples([("way", 1)], names=["element", "id"]),
    )
    monkeypatch.setattr(osm.ox, "features_from_polygon", Mock(return_value=data))
    monkeypatch.setattr(osm.ox.settings, "cache_folder", tmp_path)
    monkeypatch.setattr(osm.ox.settings, "use_cache", True)
    csv_path = tmp_path / "roads.csv"
    assert osm.OsmClient().fetch_roads_to_csv(POLYGON, csv_path) == 0
    assert pd.read_csv(csv_path).empty


@pytest.mark.parametrize("fail", [False, True])
def test_runner_delegates_and_always_closes_engine(settings, monkeypatch, fail):
    settings.database_url = SecretStr("postgresql://test-only")
    engine, session = MagicMock(), MagicMock(spec=Session)
    factory = MagicMock()
    factory.return_value.__enter__.return_value = session
    monkeypatch.setattr(import_all, "create_engine", Mock(return_value=engine))
    monkeypatch.setattr(import_all, "Session", factory)
    monkeypatch.setattr(import_all.BaseModel.metadata, "create_all", Mock())
    boundary_service = Mock(spec=boundaries.BoundaryService)
    boundary_service.import_data.return_value = {"created": 1}
    if fail:
        boundary_service.import_data.side_effect = RuntimeError("boundary write failed")
    road_service = Mock(spec=RoadService)
    road_service.import_data.return_value = 0
    boundary_factory = Mock(return_value=boundary_service)
    road_factory = Mock(return_value=road_service)
    monkeypatch.setattr(import_all, "get_boundary_service", boundary_factory)
    monkeypatch.setattr(import_all, "get_road_service", road_factory)

    if fail:
        with pytest.raises(RuntimeError, match="boundary write failed"):
            import_all.main()
        road_service.import_data.assert_not_called()
        assert session.begin.return_value.__exit__.call_args.args[0] is RuntimeError
    else:
        import_all.main()
        boundary_service.import_data.assert_called_once()
        road_service.import_data.assert_called_once()
        assert boundary_service.import_data.call_args.args[0].suffix == ".kml"
        assert road_service.import_data.call_args.args[0].name == "roads"
        road_factory.assert_called_once_with(session)
    boundary_factory.assert_called_once_with(session)
    assert {"municipal_corporations", "wards", "roads"} <= import_all.BaseModel.metadata.tables.keys()
    engine.dispose.assert_called_once()
