"""Wiring shares caller-owned sessions without caching service instances."""

import subprocess
import sys
from pathlib import Path
from unittest.mock import MagicMock, Mock

import pytest
from sqlalchemy.orm import Session

from app import dependencies
from app.clients.osm import OsmClient
from app.dependencies import (
    get_boundary_service,
    get_municipal_corporations_repo,
    get_road_service,
    get_roads_repo,
    get_wards_repo,
)
from app.modules.commons.repositories.municipal_corporations_repo import MunicipalCorporationsRepo
from app.modules.commons.repositories.wards_repo import WardsRepo
from app.modules.roads.repositories.roads_repo import RoadsRepo


@pytest.mark.parametrize("provider, repo_class", [
    (get_municipal_corporations_repo, MunicipalCorporationsRepo),
    (get_wards_repo, WardsRepo),
    (get_roads_repo, RoadsRepo),
])
def test_repo_providers_use_caller_session_without_queries(provider, repo_class):
    session = MagicMock(spec=Session)
    repo = provider(session)
    assert isinstance(repo, repo_class)
    assert repo.session is session
    assert session.mock_calls == []


def test_boundary_service_injects_provider_instances(monkeypatch):
    session = MagicMock(spec=Session)
    corporations_provider = Mock(return_value=Mock(spec=MunicipalCorporationsRepo))
    wards_provider = Mock(return_value=Mock(spec=WardsRepo))
    monkeypatch.setattr(dependencies, "get_municipal_corporations_repo", corporations_provider)
    monkeypatch.setattr(dependencies, "get_wards_repo", wards_provider)

    service = get_boundary_service(session)

    assert service.corporations_repo is corporations_provider.return_value
    assert service.wards_repo is wards_provider.return_value
    corporations_provider.assert_called_once_with(session)
    wards_provider.assert_called_once_with(session)


def test_road_service_injects_provider_instances(monkeypatch):
    session = MagicMock(spec=Session)
    roads_provider = Mock(return_value=Mock(spec=RoadsRepo))
    wards_provider = Mock(return_value=Mock(spec=WardsRepo))
    osm_provider = Mock(return_value=Mock(spec=OsmClient))
    monkeypatch.setattr(dependencies, "get_roads_repo", roads_provider)
    monkeypatch.setattr(dependencies, "get_wards_repo", wards_provider)
    monkeypatch.setattr(dependencies, "get_osm_client", osm_provider)

    service = get_road_service(session)

    assert service.session is session
    assert service.roads_repo is roads_provider.return_value
    assert service.wards_repo is wards_provider.return_value
    assert service.osm_client is osm_provider.return_value
    roads_provider.assert_called_once_with(session)
    wards_provider.assert_called_once_with(session)
    osm_provider.assert_called_once_with()


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
