from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.commons.models.base import BaseModel


class BaseRepository:
    def __init__(self, session: Session, model: type[BaseModel]) -> None:
        self.session = session
        self.model = model

    def create(self, **values: Any) -> BaseModel:
        instance = self.model(**values)
        self.session.add(instance)
        self.session.flush()
        return instance

    def get_by_id(self, record_id: Any) -> BaseModel | None:
        return self.session.get(self.model, record_id)

    def get_all(self) -> list[BaseModel]:
        statement = select(self.model)
        return list(self.session.scalars(statement))

    def update(self, instance: BaseModel, **values: Any) -> BaseModel:
        for field, value in values.items():
            setattr(instance, field, value)

        self.session.flush()
        return instance

    def delete(self, instance: BaseModel) -> None:
        self.session.delete(instance)
        self.session.flush()
