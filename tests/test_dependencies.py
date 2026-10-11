"""Wiring shares caller-owned sessions without caching service instances."""

import subprocess
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from sqlalchemy.orm import Session

from app.clients.osm import OsmClient
from app.dependencies import get_boundary_service, get_road_service
from app.modules.commons.repositories.municipal_corporations_repo import MunicipalCorporationsRepo
from app.modules.commons.repositories.wards_repo import WardsRepo
from app.modules.roads.repositories.roads_repo import RoadsRepo


def test_boundary_dependencies_share_the_supplied_session():
    session = MagicMock(spec=Session)
    service = get_boundary_service(session)
    assert isinstance(service.corporations_repo, MunicipalCorporationsRepo)
    assert isinstance(service.wards_repo, WardsRepo)
    assert service.corporations_repo.session is session
    assert service.wards_repo.session is session
    session.assert_not_called()
    session.execute.assert_not_called()


def test_road_dependencies_are_not_shared_between_sessions():
    first_session, second_session = MagicMock(spec=Session), MagicMock(spec=Session)
    first = get_road_service(first_session)
    second = get_road_service(second_session)
    for service, session in [(first, first_session), (second, second_session)]:
        assert isinstance(service.roads_repo, RoadsRepo)
        assert isinstance(service.wards_repo, WardsRepo)
        assert isinstance(service.osm_client, OsmClient)
        assert service.session is session
        assert service.roads_repo.session is session
        assert service.wards_repo.session is session
        session.execute.assert_not_called()
    assert first is not second
    assert first.roads_repo is not second.roads_repo


@pytest.mark.parametrize("code", [
    "import sys; import app.main; assert 'geopandas' not in sys.modules; assert 'osmnx' not in sys.modules",
    "from app.import_all import BaseModel; assert {'municipal_corporations', 'wards', 'roads'} <= BaseModel.metadata.tables.keys()",
])
def test_imports_in_a_fresh_process(code):
    result = subprocess.run(
        [sys.executable, "-c", code], cwd=Path(__file__).resolve().parents[1],
        capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0, result.stderr
