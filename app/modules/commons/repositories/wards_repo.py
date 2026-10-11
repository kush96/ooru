"""Read and upsert wards. No file parsing or commits here."""

from uuid import uuid4

from geoalchemy2.shape import from_shape, to_shape
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.commons.models.wards import Ward


class WardsRepo:
    def __init__(self, session: Session):
        self.session = session

    def get_boundaries(self) -> list:
        return [to_shape(boundary) for boundary in self.session.scalars(select(Ward.boundary))]

    def upsert_many(self, records: list[dict]) -> dict[str, int]:
        # Ward numbers repeat across corporations. Use names only for unresolved FKs.
        existing = {
            (ward.authorised_municipal_corporation_id, ward.source_id,
             ward.name if ward.authorised_municipal_corporation_id is None else None): ward
            for ward in self.session.scalars(select(Ward))
        }
        counts = {"created": 0, "updated": 0}
        for record in records:
            corporation_id = record["authorised_municipal_corporation_id"]
            source_id, name = record["source_id"], record["name"]
            key = (corporation_id, source_id, name if corporation_id is None else None)
            unresolved_key = (None, source_id, name)
            ward = existing.get(key) or existing.get(unresolved_key)
            if ward is None:
                ward = Ward(id=uuid4())
                self.session.add(ward)
                counts["created"] += 1
            else:
                counts["updated"] += 1
            if corporation_id is not None and existing.get(unresolved_key) is ward:
                existing.pop(unresolved_key)
            existing[key] = ward

            ward.authorised_municipal_corporation_id = corporation_id
            ward.source_id = source_id
            ward.name = name
            ward.total_population = record["total_population"]
            ward.total_male_population = record["total_male_population"]
            ward.total_female_population = record["total_female_population"]
            ward.boundary = from_shape(record["boundary"], srid=4326)
        self.session.flush()
        return counts
