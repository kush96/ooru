from sqlalchemy import Text
from sqlalchemy.orm import Mapped, mapped_column

from app.modules.commons.models.base import BaseModel


class MunicipalCorporation(BaseModel):
    __tablename__ = "municipal_corporations"
    source_id: Mapped[str] = mapped_column(Text, unique=True)
    name: Mapped[str] = mapped_column(Text, unique=True)
    name_kannada: Mapped[str | None] = mapped_column(Text, nullable=True)
    official_website: Mapped[str] = mapped_column(Text)
