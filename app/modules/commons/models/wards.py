import uuid

from geoalchemy2 import Geometry, WKBElement
from sqlalchemy import UUID, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.modules.commons.models.base import BaseModel


class Ward(BaseModel):
    __tablename__ = "wards"
    __table_args__ = (
        UniqueConstraint("authorised_municipal_corporation_id", "source_id", name="uq_ward_corporation_source_id"),
    )
    source_id: Mapped[int] = mapped_column(Integer)
    name: Mapped[str] = mapped_column(String)
    authorised_municipal_corporation_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("municipal_corporations.id"), nullable=True)
    total_population: Mapped[int] = mapped_column(Integer)
    total_male_population: Mapped[int] = mapped_column(Integer)
    total_female_population: Mapped[int] = mapped_column(Integer)
    boundary: Mapped[WKBElement] = mapped_column(
        Geometry("MULTIPOLYGON", srid=4326, spatial_index=True), nullable=False
    )
