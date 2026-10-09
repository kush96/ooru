from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.commons.models.municipal_corporations import MunicipalCorporation


CORPORATIONS = [
    ("1", "Bengaluru Central City Corporation", "https://bengalurucentral.karnataka.gov.in/"),
    ("2", "Bengaluru North City Corporation", "https://bengalurunorth.karnataka.gov.in/"),
    ("3", "Bengaluru East City Corporation", "https://bengalurueast.karnataka.gov.in/"),
    ("4", "Bengaluru South City Corporation", "https://bengalurusouth.karnataka.gov.in/"),
    ("5", "Bengaluru West City Corporation", "https://bengaluruwest.karnataka.gov.in/"),
]


def import_municipal_corporations(session: Session) -> int:
    """Insert missing corporations. The caller controls commit/rollback."""
    existing = {
        corporation.name: corporation
        for corporation in session.scalars(select(MunicipalCorporation))
    }
    created = 0
    for source_id, name, website in CORPORATIONS:
        corporation = existing.get(name)
        if corporation is None:
            corporation = MunicipalCorporation(id=uuid4(), name=name)
            session.add(corporation)
            created += 1
        corporation.source_id = source_id
        corporation.official_website = website

    session.flush()
    return created
