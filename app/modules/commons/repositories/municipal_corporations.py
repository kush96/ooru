from sqlalchemy.orm import Session

from app.modules.commons.repositories.base_repositories import BaseRepository
from app.modules.commons.models.municipal_corporations import MunicipalCorporation


class MunicipalCorporationRepo(BaseRepository):
    def __init__(self, session: Session) -> None:
        super().__init__(session, MunicipalCorporation)
