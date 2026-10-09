import uuid
from datetime import datetime, UTC

from sqlalchemy import UUID, DateTime, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class BaseModel(DeclarativeBase):
    id : Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    created_at : Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default= func.now())
    update_at : Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), server_onupdate= func.now())
    deleted_at : Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
