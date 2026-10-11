"""Service wiring for HTTP routes and CLI commands. No global service/session objects."""

from __future__ import annotations

from typing import Annotated, TYPE_CHECKING

from fastapi import Depends

from app.clients.llm import LLMClient
from app.config import Settings, get_settings
from app.modules.chat.chat_service import ChatService

if TYPE_CHECKING:
    from sqlalchemy.orm import Session
    from app.modules.commons.boundary_service import BoundaryService
    from app.modules.roads.road_service import RoadService


def get_chat_service(settings: Annotated[Settings, Depends(get_settings)]) -> ChatService:
    return ChatService(llm_client=LLMClient(settings))


def get_boundary_service(session: Session) -> BoundaryService:
    # Load data-import libraries only when the CLI needs them, not on chat startup.
    from app.modules.commons.boundary_service import BoundaryService
    from app.modules.commons.repositories.municipal_corporations_repo import MunicipalCorporationsRepo
    from app.modules.commons.repositories.wards_repo import WardsRepo

    return BoundaryService(
        corporations_repo=MunicipalCorporationsRepo(session), wards_repo=WardsRepo(session),
    )


def get_road_service(session: Session) -> RoadService:
    from app.clients.osm import OsmClient
    from app.modules.commons.repositories.wards_repo import WardsRepo
    from app.modules.roads.repositories.roads_repo import RoadsRepo
    from app.modules.roads.road_service import RoadService

    return RoadService(
        session=session, roads_repo=RoadsRepo(session),
        wards_repo=WardsRepo(session), osm_client=OsmClient(),
    )
