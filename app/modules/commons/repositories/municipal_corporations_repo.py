"""Read and upsert municipal corporations. The caller owns the transaction."""

from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.commons.models.municipal_corporations import MunicipalCorporation


class MunicipalCorporationsRepo:
    def __init__(self, session: Session):
        self.session = session

    def get_ids_by_source_id(self) -> dict[str, UUID]:
        rows = self.session.execute(select(MunicipalCorporation.source_id, MunicipalCorporation.id))
        return dict(rows.all())

    def upsert_many(self, records: list[dict]) -> int:
        existing = {item.name: item for item in self.session.scalars(select(MunicipalCorporation))}
        created = 0
        for record in records:
            corporation = existing.get(record["name"])
            if corporation is None:
                corporation = MunicipalCorporation(id=uuid4(), **record)
                self.session.add(corporation)
                existing[corporation.name] = corporation
                created += 1
            else:
                corporation.source_id = record["source_id"]
                corporation.official_website = record["official_website"]
        self.session.flush()
        return created
