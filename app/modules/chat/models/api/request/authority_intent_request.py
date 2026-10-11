from pydantic import BaseModel, ConfigDict

from app.modules.chat.models.api.common.text_constraints import MessageText


class AuthorityIntentRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    prompt: MessageText
